# 01_district_features_from_osm.py
# Базовые признаки по районам/муниципальным образованиям Москвы из OSM (без walk-метрик).
# Вход:  moscow-latest.osm.pbf
# Выход: pvz_project/district_features.csv и pvz_project/district_features.gpkg

from pathlib import Path
from time import perf_counter
import json

import pandas as pd
import geopandas as gpd
import requests
from pyrosm import OSM


# ====== НАСТРОЙКИ ======
PBF_PATH = Path(r"C:\Users\sgs-w\Downloads\moscow-latest.osm.pbf")  # <-- твой PBF
PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")
PROJECT_DIR.mkdir(parents=True, exist_ok=True)

# 1) GIS-Lab (OSM-based), муниципальные образования (146) — обычно доступнее, чем GitHub raw
# 2) GitHub raw + jsdelivr — как резерв
DISTRICTS_URLS = [
    "https://gis-lab.info/data/mos-adm/mo.geojson",
    "http://gis-lab.info/data/mos-adm/mo.geojson",
    "https://raw.githubusercontent.com/ggolikov/cities-comparison/master/src/moscow-districts.geo.json",
    "https://cdn.jsdelivr.net/gh/ggolikov/cities-comparison@master/src/moscow-districts.geo.json",
]

DISTRICTS_GEOJSON = PROJECT_DIR / "moscow_districts.geojson"

OUT_CSV = PROJECT_DIR / "district_features.csv"
OUT_GPKG = PROJECT_DIR / "district_features.gpkg"

# Метрика для площадей/длин (UTM 37N подходит для Москвы)
METRIC_CRS = "EPSG:32637"
# =======================


def _parse_geojson_bytes(b: bytes) -> dict | None:
    for enc in ("utf-8-sig", "utf-8"):
        try:
            obj = json.loads(b.decode(enc, errors="strict"))
            if isinstance(obj, dict) and obj.get("type") == "FeatureCollection" and isinstance(obj.get("features"), list):
                return obj
        except Exception:
            pass
    return None


def download_geojson_verified(urls, path: Path) -> str:
    # если файл уже есть и валидный — не трогаем
    if path.exists():
        try:
            b = path.read_bytes()
            if _parse_geojson_bytes(b) is not None:
                return "local_cache"
        except Exception:
            pass
        try:
            path.unlink()
        except Exception:
            pass

    headers = {
        "User-Agent": "pvz-diploma/1.0",
        "Accept": "application/json,text/plain,*/*",
        "Cache-Control": "no-cache",
    }

    last_preview = None
    last_err = None

    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=120, allow_redirects=True)
            r.raise_for_status()
            b = r.content

            obj = _parse_geojson_bytes(b)
            if obj is None or len(obj.get("features", [])) == 0:
                # покажем кусок ответа для диагностики
                last_preview = b[:200].decode("utf-8", errors="replace")
                raise ValueError("Downloaded GeoJSON is invalid/truncated or not GeoJSON")

            path.write_bytes(b)
            return url

        except Exception as e:
            last_err = e

    msg = (
        "Не смог скачать валидный GeoJSON границ.\n"
        f"Последняя ошибка: {last_err}\n"
        f"Превью последнего ответа (первые 200 байт): {last_preview}\n"
        "Попробуй открыть в браузере и скачать вручную любой из URL:\n"
        + "\n".join(f"  - {u}" for u in urls)
        + f"\nИ сохранить как: {path}"
    )
    raise RuntimeError(msg)


def load_districts(path: Path) -> gpd.GeoDataFrame:
    obj = _parse_geojson_bytes(path.read_bytes())
    if obj is None:
        raise RuntimeError("Локальный GeoJSON районов всё ещё невалидный. Удали файл и перезапусти.")
    gdf = gpd.GeoDataFrame.from_features(obj["features"])
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    return gdf


def pick_name_col(gdf: gpd.GeoDataFrame) -> str:
    candidates = ["name", "NAME", "district", "District", "район", "RAION", "raion"]
    for c in candidates:
        if c in gdf.columns:
            return c
    for c in gdf.columns:
        if gdf[c].dtype == object:
            return c
    return gdf.columns[0]


def ensure_crs(gdf: gpd.GeoDataFrame, crs: str) -> gpd.GeoDataFrame:
    if gdf is None:
        return gpd.GeoDataFrame(geometry=[], crs=crs)
    if len(gdf) == 0:
        return gpd.GeoDataFrame(gdf, geometry="geometry", crs=crs)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    return gdf.to_crs(crs)


def get_pois_safe(osm: OSM, custom_filter: dict) -> gpd.GeoDataFrame:
    gdf = osm.get_pois(custom_filter=custom_filter)
    if gdf is None or len(gdf) == 0:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    if "geometry" not in gdf.columns:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    gdf = gdf[~gdf.geometry.isna()].copy()
    return gdf


def count_points_within(points: gpd.GeoDataFrame, polys: gpd.GeoDataFrame, key_col: str) -> pd.Series:
    if points is None or len(points) == 0:
        return pd.Series(0, index=polys[key_col])

    pts = points.to_crs(polys.crs)

    joined = gpd.sjoin(pts[["geometry"]], polys[[key_col, "geometry"]], predicate="within", how="inner")
    return joined.groupby(key_col).size()


def area_share(polys_feature: gpd.GeoDataFrame, polys_base: gpd.GeoDataFrame, key_col: str) -> pd.Series:
    if polys_feature is None or len(polys_feature) == 0:
        return pd.Series(0.0, index=polys_base[key_col])

    feat = polys_feature.to_crs(polys_base.crs).copy()
    feat = feat[feat.geometry.type.isin(["Polygon", "MultiPolygon"])]
    if len(feat) == 0:
        return pd.Series(0.0, index=polys_base[key_col])

    inter = gpd.overlay(polys_base[[key_col, "geometry"]], feat[["geometry"]], how="intersection")
    if len(inter) == 0:
        return pd.Series(0.0, index=polys_base[key_col])

    inter["a"] = inter.geometry.area
    a = inter.groupby(key_col)["a"].sum()
    base_a = polys_base.set_index(key_col).geometry.area
    return (a / base_a).reindex(polys_base[key_col]).fillna(0.0)


def main() -> None:
    t0 = perf_counter()

    print("[1/6] Download + load districts (robust) ...")
    used = download_geojson_verified(DISTRICTS_URLS, DISTRICTS_GEOJSON)
    districts = load_districts(DISTRICTS_GEOJSON)

    name_col = pick_name_col(districts)
    districts = districts.rename(columns={name_col: "district_name"}).copy()
    districts["district_name"] = districts["district_name"].astype(str)

    # стабильный ID
    districts["district_id"] = districts.index.astype(int)

    districts_m = districts.to_crs(METRIC_CRS)
    districts_m["area_km2"] = districts_m.geometry.area / 1_000_000.0

    t1 = perf_counter()
    print(f"  districts={len(districts_m):,} source={used} (dt={t1 - t0:.1f}s)")

    print("[2/6] Open PBF ...")
    osm = OSM(str(PBF_PATH))
    t2 = perf_counter()
    print(f"  ok (dt={t2 - t1:.1f}s)")

    print("[3/6] Extract OSM layers ...")
    competitors = get_pois_safe(osm, {
        "amenity": ["parcel_locker"],
        "office": ["courier"],
        "post_office": ["post_partner"],
    })

    metro = get_pois_safe(osm, {
        "railway": ["subway_entrance", "station"],
        "public_transport": ["station"],
        "station": ["subway"],
    })
    metro = metro[metro.geometry.type.isin(["Point", "MultiPoint"])].copy()

    res_buildings = get_pois_safe(osm, {
        "building": ["apartments", "residential", "house", "detached", "terrace", "semidetached_house"],
    })

    dorms = get_pois_safe(osm, {
        "building": ["dormitory"],
        "amenity": ["student_accommodation"],
    })

    cemeteries = get_pois_safe(osm, {
        "landuse": ["cemetery"],
        "amenity": ["grave_yard"],
    })

    t3 = perf_counter()
    print(
        f"  competitors={len(competitors):,}, metro={len(metro):,}, "
        f"res_buildings={len(res_buildings):,}, dorms={len(dorms):,}, cemeteries={len(cemeteries):,} "
        f"(dt={t3 - t2:.1f}s)"
    )

    print("[4/6] Aggregate by districts ...")
    key = "district_id"

    comp_cnt = count_points_within(ensure_crs(competitors, METRIC_CRS), districts_m, key)
    metro_cnt = count_points_within(ensure_crs(metro, METRIC_CRS), districts_m, key)

    res_pts = ensure_crs(res_buildings, METRIC_CRS).copy()
    res_pts["geometry"] = res_pts.geometry.centroid
    res_cnt = count_points_within(res_pts, districts_m, key)

    dorm_pts = ensure_crs(dorms, METRIC_CRS).copy()
    dorm_pts["geometry"] = dorm_pts.geometry.centroid
    dorm_cnt = count_points_within(dorm_pts, districts_m, key)

    cemetery_share = area_share(ensure_crs(cemeteries, METRIC_CRS), districts_m, key)

    if len(metro) > 0:
        metro_m = ensure_crs(metro, METRIC_CRS)
        metro_union = metro_m.unary_union
        centroids = districts_m.geometry.centroid
        metro_dist_m = centroids.distance(metro_union)
    else:
        metro_dist_m = pd.Series([float("nan")] * len(districts_m), index=districts_m.index)

    comp_cnt = comp_cnt.reindex(districts_m[key]).fillna(0).astype(int)
    metro_cnt = metro_cnt.reindex(districts_m[key]).fillna(0).astype(int)
    res_cnt = res_cnt.reindex(districts_m[key]).fillna(0).astype(int)
    dorm_cnt = dorm_cnt.reindex(districts_m[key]).fillna(0).astype(int)
    cemetery_share = cemetery_share.reindex(districts_m[key]).fillna(0.0)

    t4 = perf_counter()
    print(f"  ok (dt={t4 - t3:.1f}s)")

    print("[5/6] Build output table ...")
    out = districts_m[[key, "district_name", "area_km2"]].copy()

    out["competitor_cnt"] = comp_cnt.values
    out["competitor_density_km2"] = out["competitor_cnt"] / out["area_km2"].replace(0, pd.NA)

    out["metro_cnt"] = metro_cnt.values
    out["metro_density_km2"] = out["metro_cnt"] / out["area_km2"].replace(0, pd.NA)
    out["metro_dist_m_centroid"] = metro_dist_m.values

    out["res_buildings_cnt"] = res_cnt.values
    out["res_buildings_density_km2"] = out["res_buildings_cnt"] / out["area_km2"].replace(0, pd.NA)

    out["dormitory_cnt"] = dorm_cnt.values
    out["cemetery_area_share"] = cemetery_share.values

    out_gdf = gpd.GeoDataFrame(out, geometry=districts_m.geometry, crs=METRIC_CRS)

    t5 = perf_counter()
    print(f"  ok (dt={t5 - t4:.1f}s)")

    print("[6/6] Save CSV + GPKG ...")
    out_gdf.to_file(OUT_GPKG, layer="districts_features", driver="GPKG")

    if len(competitors) > 0:
        ensure_crs(competitors, METRIC_CRS).to_file(OUT_GPKG, layer="competitors_osm", driver="GPKG")
    if len(metro) > 0:
        ensure_crs(metro, METRIC_CRS).to_file(OUT_GPKG, layer="metro_osm", driver="GPKG")

    out_gdf.drop(columns=["geometry"], errors="ignore").to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    t6 = perf_counter()
    print("DONE")
    print("CSV :", OUT_CSV)
    print("GPKG:", OUT_GPKG)
    print(f"TOTAL dt={t6 - t0:.1f}s)")


if __name__ == "__main__":
    main()
