# 05_make_demand_and_candidates.py
# Делает:
# 1) demand points (агрегированный спрос) по сетке внутри TOP_K полигонов
#    вес = сколько жилых зданий попадает в радиус DEM_RADIUS_M вокруг demand-точки
# 2) candidate points (кандидаты ПВЗ) по более редкой сетке внутри тех же полигонов
#
# Вход:
#   - pvz_project/district_index_v2.gpkg (layer: districts_index_v2)
#   - moscow-latest.osm.pbf
# Выход:
#   - pvz_project/demand_points.gpkg + .csv
#   - pvz_project/candidate_points.gpkg + .csv

from pathlib import Path
from time import perf_counter
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from pyrosm import OSM

# ====== НАСТРОЙКИ ======
PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

IN_INDEX_GPKG = PROJECT_DIR / "district_index_v2.gpkg"
IN_INDEX_LAYER = "districts_index_v2"

PBF_PATH = Path(r"C:\Users\sgs-w\Downloads\moscow-latest.osm.pbf")

OUT_DEMAND_GPKG = PROJECT_DIR / "demand_points.gpkg"
OUT_DEMAND_LAYER = "demand_points"
OUT_DEMAND_CSV = PROJECT_DIR / "demand_points.csv"

OUT_CAND_GPKG = PROJECT_DIR / "candidate_points.gpkg"
OUT_CAND_LAYER = "candidate_points"
OUT_CAND_CSV = PROJECT_DIR / "candidate_points.csv"

METRIC_CRS = "EPSG:32637"
WGS84 = "EPSG:4326"

TOP_K = 20              # сколько лучших полигонов берём для дальнейшего поиска ПВЗ
DEMAND_STEP_M = 250     # шаг сетки для demand (м)
DEMAND_RADIUS_M = 200   # радиус агрегации спроса вокруг demand-точки (м)
CAND_STEP_M = 400       # шаг сетки для кандидатов (м)
MIN_DEMAND_W = 3        # отсечь demand-точки с маленьким весом (шум)
# =======================


def grid_points_within_polygon(poly, step_m: float):
    minx, miny, maxx, maxy = poly.bounds
    xs = np.arange(minx, maxx + step_m, step_m)
    ys = np.arange(miny, maxy + step_m, step_m)
    pts = []
    for x in xs:
        for y in ys:
            p = Point(float(x), float(y))
            if poly.contains(p):
                pts.append(p)
    return pts


def ensure_gdf_crs(gdf, crs):
    if gdf.crs is None:
        gdf = gdf.set_crs(WGS84, allow_override=True)
    return gdf.to_crs(crs)


def main():
    t0 = perf_counter()

    print("[1/6] Load top polygons ...")
    polys = gpd.read_file(IN_INDEX_GPKG, layer=IN_INDEX_LAYER)
    if polys.crs is None:
        polys = polys.set_crs(METRIC_CRS, allow_override=True)

    polys = polys.sort_values("index_rank").copy()
    top = polys[polys["index_rank"] <= TOP_K].copy()
    top_m = top.to_crs(METRIC_CRS)

    # union для фильтрации
    top_union = top_m.unary_union

    t1 = perf_counter()
    print(f"  top_polygons={len(top_m)} (dt={t1 - t0:.1f}s)")

    print("[2/6] Load residential buildings from PBF ...")
    osm = OSM(str(PBF_PATH))

    # жилые здания как прокси спроса
    res = osm.get_pois(custom_filter={
        "building": ["apartments", "residential", "house", "detached", "terrace", "semidetached_house"],
    })

    if res is None or len(res) == 0 or "geometry" not in res.columns:
        raise RuntimeError("Не удалось извлечь жилые здания из PBF (building=*).")

    if res.crs is None:
        res = res.set_crs(WGS84, allow_override=True)

    res_m = res.to_crs(METRIC_CRS).copy()
    res_m = res_m[~res_m.geometry.isna()].copy()

    # полигоны -> центроиды
    res_m["geometry"] = res_m.geometry.centroid

    # оставляем только внутри union TOP_K
    res_m = res_m[res_m.geometry.within(top_union)].copy()

    t2 = perf_counter()
    print(f"  res_buildings_in_top={len(res_m):,} (dt={t2 - t1:.1f}s)")

    print("[3/6] Build demand grid points ...")
    demand_pts = []
    demand_owner = []
    for _, row in top_m.iterrows():
        poly = row.geometry
        name = str(row.get("district_name", ""))
        pts = grid_points_within_polygon(poly, DEMAND_STEP_M)
        demand_pts.extend(pts)
        demand_owner.extend([name] * len(pts))

    demand = gpd.GeoDataFrame(
        {"district_name": demand_owner},
        geometry=demand_pts,
        crs=METRIC_CRS
    )

    t3 = perf_counter()
    print(f"  demand_grid_points={len(demand):,} (dt={t3 - t2:.1f}s)")

    print("[4/6] Aggregate demand weights (count residential buildings within radius) ...")
    # буферы вокруг demand-точек
    demand_buf = demand.copy()
    demand_buf["geometry"] = demand_buf.geometry.buffer(DEMAND_RADIUS_M)

    # sjoin: точки зданий внутри буфера
    joined = gpd.sjoin(res_m[["geometry"]], demand_buf[["district_name", "geometry"]], predicate="within", how="inner")
    # joined.index_right -> индексы буферов demand_buf
    w = joined.groupby("index_right").size()

    demand["demand_w"] = demand.index.map(w).fillna(0).astype(int)

    # чистим шум
    demand = demand[demand["demand_w"] >= MIN_DEMAND_W].copy()

    t4 = perf_counter()
    print(f"  demand_points_after_filter={len(demand):,} (dt={t4 - t3:.1f}s)")

    print("[5/6] Build candidate grid points ...")
    cand_pts = []
    cand_owner = []
    for _, row in top_m.iterrows():
        poly = row.geometry
        name = str(row.get("district_name", ""))
        pts = grid_points_within_polygon(poly, CAND_STEP_M)
        cand_pts.extend(pts)
        cand_owner.extend([name] * len(pts))

    candidates = gpd.GeoDataFrame(
        {"district_name": cand_owner},
        geometry=cand_pts,
        crs=METRIC_CRS
    )

    t5 = perf_counter()
    print(f"  candidate_points={len(candidates):,} (dt={t5 - t4:.1f}s)")

    print("[6/6] Save outputs ...")
    # сохраняем в metric CRS + отдельные CSV в WGS84 для следующего шага (привязка к графу)
    demand_wgs = demand.to_crs(WGS84)
    cand_wgs = candidates.to_crs(WGS84)

    demand.to_file(OUT_DEMAND_GPKG, layer=OUT_DEMAND_LAYER, driver="GPKG")
    candidates.to_file(OUT_CAND_GPKG, layer=OUT_CAND_LAYER, driver="GPKG")

    # CSV: lat/lon
    demand_csv = pd.DataFrame({
        "district_name": demand_wgs["district_name"].astype(str),
        "lat": demand_wgs.geometry.y.astype(float),
        "lon": demand_wgs.geometry.x.astype(float),
        "demand_w": demand_wgs["demand_w"].astype(int),
    })
    cand_csv = pd.DataFrame({
        "district_name": cand_wgs["district_name"].astype(str),
        "lat": cand_wgs.geometry.y.astype(float),
        "lon": cand_wgs.geometry.x.astype(float),
    })

    demand_csv.to_csv(OUT_DEMAND_CSV, index=False, encoding="utf-8-sig")
    cand_csv.to_csv(OUT_CAND_CSV, index=False, encoding="utf-8-sig")

    t6 = perf_counter()
    print("DONE")
    print("DEMAND GPKG:", OUT_DEMAND_GPKG)
    print("DEMAND CSV :", OUT_DEMAND_CSV)
    print("CAND  GPKG:", OUT_CAND_GPKG)
    print("CAND  CSV :", OUT_CAND_CSV)
    print(f"TOTAL dt={t6 - t0:.1f}s)")


if __name__ == "__main__":
    main()
