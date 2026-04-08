# 05_make_demand_and_candidates_v2.py
# Citywide demand/candidates с более адекватной прокси спроса:
# demand_w = sum( building_area_m2 * building_levels ) вокруг demand-точки.
#
# Вход:
#   - pvz_project/district_index_v2.gpkg (layer: districts_index_v2)  (полигоны Москвы)
#   - moscow-latest.osm.pbf
# Выход (перезапишет):
#   - pvz_project/demand_points.gpkg + .csv
#   - pvz_project/candidate_points.gpkg + .csv
#   - pvz_project/demand_by_district.csv (диагностика)

from pathlib import Path
from time import perf_counter
import re
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

OUT_DIAG = PROJECT_DIR / "demand_by_district.csv"

METRIC_CRS = "EPSG:32637"
WGS84 = "EPSG:4326"

DEMAND_STEP_M = 300       # шаг сетки demand по городу (чем меньше, тем тяжелее)
DEMAND_RADIUS_M = 250     # радиус агрегации спроса
CAND_STEP_M = 500         # шаг сетки кандидатов
CAND_BUFFER_M = 1200      # кандидаты оставляем только близко к спросу (ускорение)
MAX_CANDIDATES = 6000     # чтобы 06 не умер по времени

# пороги для demand
MIN_DEMAND_W_ABS = 50_000     # минимальный спрос (м2*этажи) чтобы оставить точку
MIN_DEMAND_W_Q = 0.40         # или квантиль: оставим точки выше этого квантиля
# =======================


_levels_re = re.compile(r"^\s*(\d+)")


def parse_levels(v):
    if v is None:
        return 1
    if isinstance(v, (int, float)) and np.isfinite(v):
        return max(int(v), 1)
    if isinstance(v, str):
        m = _levels_re.match(v)
        if m:
            return max(int(m.group(1)), 1)
    return 1


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


def main():
    t0 = perf_counter()

    print("[1/7] Load Moscow polygons (all) ...")
    polys = gpd.read_file(IN_INDEX_GPKG, layer=IN_INDEX_LAYER)
    if polys.crs is None:
        polys = polys.set_crs(METRIC_CRS, allow_override=True)
    polys_m = polys.to_crs(METRIC_CRS).copy()
    moscow_union = polys_m.unary_union
    print(f"  polygons={len(polys_m):,}")
    t1 = perf_counter()
    print(f"  ok (dt={t1 - t0:.1f}s)")

    print("[2/7] Load buildings from PBF (polygons) ...")
    osm = OSM(str(PBF_PATH))
    b = osm.get_buildings()
    if b is None or len(b) == 0:
        raise RuntimeError("pyrosm.get_buildings() вернул пусто. Проверь PBF.")
    if b.crs is None:
        b = b.set_crs(WGS84, allow_override=True)
    b = b.to_crs(METRIC_CRS)

    b = b[b.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
    b = b[~b.geometry.isna()].copy()

    # ограничим Москвой
    b = b[b.geometry.intersects(moscow_union)].copy()

    # оставим жилые типы (как минимум)
    # в OSM это поле "building"
    if "building" not in b.columns:
        raise RuntimeError("В buildings нет колонки 'building' — странно для pyrosm.")
    res_types = {
        "apartments", "residential", "house", "detached", "terrace", "semidetached_house", "dormitory"
    }
    b = b[b["building"].astype(str).str.lower().isin(res_types)].copy()

    # площадь * этажность
    b["area_m2"] = b.geometry.area.astype(float)
    levels_col = None
    for c in ["building:levels", "levels", "building_levels"]:
        if c in b.columns:
            levels_col = c
            break
    if levels_col is None:
        b["levels"] = 1
    else:
        b["levels"] = b[levels_col].apply(parse_levels).astype(int)

    b["floor_area_proxy"] = (b["area_m2"] * b["levels"]).astype(float)

    # точки зданий = центроиды для join within буферов
    b_pts = b[["floor_area_proxy", "geometry"]].copy()
    b_pts["geometry"] = b_pts.geometry.centroid

    t2 = perf_counter()
    print(f"  residential_buildings={len(b_pts):,} (dt={t2 - t1:.1f}s)")

    print("[3/7] Build demand grid (citywide) ...")
    demand_pts = []
    demand_owner = []
    for _, row in polys_m.iterrows():
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

    print("[4/7] Aggregate demand_w = sum(floor_area_proxy) within radius ...")
    demand_buf = demand.copy()
    demand_buf["geometry"] = demand_buf.geometry.buffer(DEMAND_RADIUS_M)

    joined = gpd.sjoin(
        b_pts,
        demand_buf[["district_name", "geometry"]],
        predicate="within",
        how="inner",
    )
    # index_right -> индекс demand_buf
    w = joined.groupby("index_right")["floor_area_proxy"].sum()

    demand["demand_w"] = demand.index.map(w).fillna(0.0).astype(float)

    # фильтрация: одновременно абсолютный порог и квантиль
    q_thr = float(demand["demand_w"].quantile(MIN_DEMAND_W_Q))
    thr = max(float(MIN_DEMAND_W_ABS), q_thr)
    demand = demand[demand["demand_w"] >= thr].copy()

    t4 = perf_counter()
    print(f"  demand_points_after_filter={len(demand):,} thr={thr:,.0f} (dt={t4 - t3:.1f}s)")

    print("[5/7] Build candidate grid + prefilter by demand proximity ...")
    cand_pts = []
    cand_owner = []
    for _, row in polys_m.iterrows():
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

    # оставляем кандидатов только близко к спросу
    demand_union = demand.geometry.buffer(CAND_BUFFER_M).unary_union
    candidates = candidates[candidates.geometry.intersects(demand_union)].copy()

    t5 = perf_counter()
    print(f"  candidates_after_proximity={len(candidates):,} (dt={t5 - t4:.1f}s)")

    print("[6/7] If too many candidates, keep those with highest local demand ...")
    if len(candidates) > MAX_CANDIDATES:
        # local demand = сумма demand_w в радиусе CAND_BUFFER_M
        cand_buf = candidates.copy()
        cand_buf["geometry"] = cand_buf.geometry.buffer(CAND_BUFFER_M)

        j2 = gpd.sjoin(
            demand[["demand_w", "geometry"]],
            cand_buf[["geometry"]],
            predicate="within",
            how="inner",
        )
        local = j2.groupby("index_right")["demand_w"].sum()
        candidates["local_demand_w"] = candidates.index.map(local).fillna(0.0).astype(float)
        candidates = candidates.sort_values("local_demand_w", ascending=False).head(MAX_CANDIDATES).copy()
    else:
        candidates["local_demand_w"] = np.nan

    t6 = perf_counter()
    print(f"  candidates_final={len(candidates):,} (dt={t6 - t5:.1f}s)")

    print("[7/7] Save outputs + district demand diagnostics ...")
    demand_wgs = demand.to_crs(WGS84)
    cand_wgs = candidates.to_crs(WGS84)

    demand.to_file(OUT_DEMAND_GPKG, layer=OUT_DEMAND_LAYER, driver="GPKG")
    candidates.to_file(OUT_CAND_GPKG, layer=OUT_CAND_LAYER, driver="GPKG")

    pd.DataFrame({
        "district_name": demand_wgs["district_name"].astype(str),
        "lat": demand_wgs.geometry.y.astype(float),
        "lon": demand_wgs.geometry.x.astype(float),
        "demand_w": demand_wgs["demand_w"].astype(float),
    }).to_csv(OUT_DEMAND_CSV, index=False, encoding="utf-8-sig")

    pd.DataFrame({
        "district_name": cand_wgs["district_name"].astype(str),
        "lat": cand_wgs.geometry.y.astype(float),
        "lon": cand_wgs.geometry.x.astype(float),
        "local_demand_w": cand_wgs.get("local_demand_w", pd.Series([np.nan]*len(cand_wgs))).astype(float),
    }).to_csv(OUT_CAND_CSV, index=False, encoding="utf-8-sig")

    # диагностика: сколько спроса (demand_w) по районам в сумме
    diag = demand.groupby("district_name")["demand_w"].sum().sort_values(ascending=False).reset_index()
    diag.to_csv(OUT_DIAG, index=False, encoding="utf-8-sig")

    t7 = perf_counter()
    print("DONE")
    print("DEMAND:", OUT_DEMAND_GPKG, OUT_DEMAND_CSV)
    print("CAND  :", OUT_CAND_GPKG, OUT_CAND_CSV)
    print("DIAG  :", OUT_DIAG)
    print(f"TOTAL dt={t7 - t0:.1f}s)")


if __name__ == "__main__":
    main()
