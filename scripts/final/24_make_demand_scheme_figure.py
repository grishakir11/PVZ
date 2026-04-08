# 24_make_demand_scheme_figure.py
# Делает рисунок для раздела 2.3:
# как из жилой застройки получается модель точек спроса.

from pathlib import Path
import geopandas as gpd
import matplotlib.pyplot as plt
from pyrosm import OSM

PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")
PBF_PATH = Path(r"C:\Users\sgs-w\Downloads\moscow-latest.osm.pbf")

DIST_GPKG = PROJECT_DIR / "district_index_v2.gpkg"
DIST_LAYER = "districts_index_v2"

DEMAND_GPKG = PROJECT_DIR / "demand_points.gpkg"
DEMAND_LAYER = "demand_points"

OUT_PNG = PROJECT_DIR / "fig_demand_model_scheme.png"

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
    print("[1/5] Load district polygon ...")
    districts = gpd.read_file(DIST_GPKG, layer=DIST_LAYER)
    if districts.crs is None:
        districts = districts.set_crs(METRIC_CRS, allow_override=True)
    districts = districts.to_crs(WGS84)

    district = pick_district(districts)
    district_name = str(district.iloc[0]["district_name"])
    district_geom = district.iloc[0].geometry

    print(f"  chosen district: {district_name}")

    print("[2/5] Load demand points and clip to district ...")
    demand = gpd.read_file(DEMAND_GPKG, layer=DEMAND_LAYER)
    if demand.crs is None:
        demand = demand.set_crs(METRIC_CRS, allow_override=True)
    demand = demand.to_crs(WGS84)

    demand_clip = demand[demand.intersects(district_geom)].copy()
    if len(demand_clip) == 0:
        raise RuntimeError("В выбранном районе не найдено точек спроса")

    print(f"  demand points in district: {len(demand_clip)}")

    print("[3/5] Load residential buildings from OSM PBF ...")
    osm = OSM(str(PBF_PATH))
    buildings = osm.get_buildings()
    if buildings is None or len(buildings) == 0:
        raise RuntimeError("Не удалось извлечь здания из PBF")

    if buildings.crs is None:
        buildings = buildings.set_crs(WGS84, allow_override=True)
    else:
        buildings = buildings.to_crs(WGS84)

    # оставляем только жилые типы
    if "building" in buildings.columns:
        residential_tags = {
            "apartments", "residential", "house", "detached", "semidetached_house",
            "terrace", "dormitory", "yes"
        }
        buildings = buildings[buildings["building"].astype(str).isin(residential_tags)].copy()

    buildings_clip = buildings[buildings.intersects(district_geom)].copy()
    if len(buildings_clip) == 0:
        raise RuntimeError("В выбранном районе не найдено жилых зданий")

    print(f"  residential buildings in district: {len(buildings_clip)}")

    print("[4/5] Plot ...")
    fig, axes = plt.subplots(1, 3, figsize=(16, 6))

    # Панель 1: здания
    district.boundary.plot(ax=axes[0], linewidth=1)
    buildings_clip.plot(ax=axes[0], linewidth=0.2)
    axes[0].set_title("а) Жилая застройка")
    axes[0].set_axis_off()

    # Панель 2: точки спроса
    district.boundary.plot(ax=axes[1], linewidth=1)
    size_col = None
    for c in ["demand_w", "weight", "value"]:
        if c in demand_clip.columns:
            size_col = c
            break

    if size_col is None:
        demand_clip.plot(ax=axes[1], markersize=8)
    else:
        vals = demand_clip[size_col].fillna(0)
        sizes = 5 + 45 * (vals / vals.max())
        demand_clip.plot(ax=axes[1], markersize=sizes)
    axes[1].set_title("б) Точки спроса")
    axes[1].set_axis_off()

    # Панель 3: совмещение
    district.boundary.plot(ax=axes[2], linewidth=1)
    buildings_clip.plot(ax=axes[2], linewidth=0.2)
    if size_col is None:
        demand_clip.plot(ax=axes[2], markersize=8)
    else:
        demand_clip.plot(ax=axes[2], markersize=sizes)
    axes[2].set_title("в) Здания и точки спроса")
    axes[2].set_axis_off()

    plt.suptitle(f"Формирование модели спроса на примере района {district_name}")
    plt.tight_layout()
    plt.savefig(OUT_PNG, dpi=220)
    plt.close()

    print("[5/5] Done")
    print("PNG:", OUT_PNG)


if __name__ == "__main__":
    main()
