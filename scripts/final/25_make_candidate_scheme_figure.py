# 25_make_candidate_scheme_figure.py
# Делает рисунок для раздела 2.4:
# как выглядит множество кандидатных локаций для ПВЗ
# на фоне точек спроса.

from pathlib import Path
import geopandas as gpd
import matplotlib.pyplot as plt

PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

DIST_GPKG = PROJECT_DIR / "district_index_v2.gpkg"
DIST_LAYER = "districts_index_v2"

DEMAND_GPKG = PROJECT_DIR / "demand_points.gpkg"
DEMAND_LAYER = "demand_points"

CAND_GPKG = PROJECT_DIR / "candidate_points.gpkg"
CAND_LAYER = "candidate_points"

OUT_PNG = PROJECT_DIR / "fig_candidate_points_scheme.png"

TARGET_DISTRICT = "Таганский"
WGS84 = "EPSG:4326"
METRIC_CRS = "EPSG:32637"


def pick_district(districts: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if "district_name" not in districts.columns:
        raise RuntimeError("В district_index_v2.gpkg нет колонки district_name")

    hit = districts[districts["district_name"].astype(str) == TARGET_DISTRICT].copy()
    if len(hit) > 0:
        return hit.iloc[[0]].copy()

    return districts.iloc[[0]].copy()


def main():
    print("[1/4] Load district polygon ...")
    districts = gpd.read_file(DIST_GPKG, layer=DIST_LAYER)
    if districts.crs is None:
        districts = districts.set_crs(METRIC_CRS, allow_override=True)
    districts = districts.to_crs(WGS84)

    district = pick_district(districts)
    district_name = str(district.iloc[0]["district_name"])
    district_geom = district.iloc[0].geometry

    print(f"  chosen district: {district_name}")

    print("[2/4] Load demand and candidate points ...")
    demand = gpd.read_file(DEMAND_GPKG, layer=DEMAND_LAYER)
    cand = gpd.read_file(CAND_GPKG, layer=CAND_LAYER)

    if demand.crs is None:
        demand = demand.set_crs(METRIC_CRS, allow_override=True)
    if cand.crs is None:
        cand = cand.set_crs(METRIC_CRS, allow_override=True)

    demand = demand.to_crs(WGS84)
    cand = cand.to_crs(WGS84)

    demand_clip = demand[demand.intersects(district_geom)].copy()
    cand_clip = cand[cand.intersects(district_geom)].copy()

    if len(demand_clip) == 0:
        raise RuntimeError("В выбранном районе нет точек спроса")
    if len(cand_clip) == 0:
        raise RuntimeError("В выбранном районе нет кандидатных точек")

    print(f"  demand points: {len(demand_clip)}")
    print(f"  candidate points: {len(cand_clip)}")

    print("[3/4] Plot ...")
    fig, axes = plt.subplots(1, 3, figsize=(16, 6))

    # Панель 1: точки спроса
    district.boundary.plot(ax=axes[0], linewidth=1)
    if "demand_w" in demand_clip.columns:
        vals = demand_clip["demand_w"].fillna(0)
        sizes = 5 + 45 * (vals / vals.max())
        demand_clip.plot(ax=axes[0], markersize=sizes)
    else:
        demand_clip.plot(ax=axes[0], markersize=8)
    axes[0].set_title("а) Точки спроса")
    axes[0].set_axis_off()

    # Панель 2: кандидаты
    district.boundary.plot(ax=axes[1], linewidth=1)
    cand_clip.plot(ax=axes[1], markersize=6)
    axes[1].set_title("б) Кандидатные локации")
    axes[1].set_axis_off()

    # Панель 3: вместе
    district.boundary.plot(ax=axes[2], linewidth=1)
    cand_clip.plot(ax=axes[2], markersize=5)
    if "demand_w" in demand_clip.columns:
        demand_clip.plot(ax=axes[2], markersize=sizes)
    else:
        demand_clip.plot(ax=axes[2], markersize=8)
    axes[2].set_title("в) Спрос и кандидаты")
    axes[2].set_axis_off()

    plt.suptitle(f"Формирование множества кандидатных локаций на примере района {district_name}")
    plt.tight_layout()
    plt.savefig(OUT_PNG, dpi=220)
    plt.close()

    print("[4/4] Done")
    print("PNG:", OUT_PNG)


if __name__ == "__main__":
    main()
