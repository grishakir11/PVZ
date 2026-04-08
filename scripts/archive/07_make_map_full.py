# 07_make_map_full.py
# Интерактивная карта (HTML):
# - Хороплет по index_score_0_1 (полигоны)
# - Heatmap спроса (demand_points)
# - Точки выбранных ПВЗ (pvz_selected_20)
#
# Вход:
#   pvz_project/district_index_v2.gpkg (layer: districts_index_v2)
#   pvz_project/demand_points.gpkg (layer: demand_points)
#   pvz_project/pvz_selected_20.gpkg (layer: pvz_selected_20)
#
# Выход:
#   pvz_project/map_full_pvz20.html

from pathlib import Path
import math

import geopandas as gpd
import pandas as pd
import folium
from folium.features import GeoJsonTooltip
from folium.plugins import HeatMap
import branca.colormap as cm


# ====== НАСТРОЙКИ ======
PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

INDEX_GPKG = PROJECT_DIR / "district_index_v2.gpkg"
INDEX_LAYER = "districts_index_v2"

DEMAND_GPKG = PROJECT_DIR / "demand_points.gpkg"
DEMAND_LAYER = "demand_points"
DEMAND_CSV = PROJECT_DIR / "demand_points.csv"  # fallback

PVZ_GPKG = PROJECT_DIR / "pvz_selected_20.gpkg"
PVZ_LAYER = "pvz_selected_20"
PVZ_CSV = PROJECT_DIR / "pvz_selected_20.csv"  # fallback

OUT_HTML = PROJECT_DIR / "map_full_pvz20.html"

# если demand точек слишком много и браузер лагает:
MAX_HEAT_POINTS = 60000   # None чтобы не ограничивать
HEAT_RADIUS = 12
HEAT_BLUR = 18
HEAT_MIN_OPACITY = 0.25

# точки ПВЗ
PVZ_RADIUS = 6

WGS84 = "EPSG:4326"
# =======================


def load_gpkg_or_csv_points(gpkg_path: Path, layer: str, csv_path: Path, lat_col="lat", lon_col="lon"):
    if gpkg_path.exists():
        gdf = gpd.read_file(gpkg_path, layer=layer)
        if gdf.crs is None:
            # у тебя все точки сохранялись в метрике; если CRS потерялся — лучше явно считать WGS84 и не врать
            raise RuntimeError(f"{gpkg_path} layer={layer}: CRS is missing.")
        return gdf
    if csv_path.exists():
        df = pd.read_csv(csv_path, encoding="utf-8-sig")
        if lat_col not in df.columns or lon_col not in df.columns:
            raise RuntimeError(f"{csv_path}: нет колонок {lat_col}/{lon_col}")
        return gpd.GeoDataFrame(
            df,
            geometry=gpd.points_from_xy(df[lon_col], df[lat_col], crs=WGS84),
        )
    raise RuntimeError(f"Не найден ни {gpkg_path} (layer={layer}), ни {csv_path}")


def main():
    # --- индексовые полигоны ---
    gdf = gpd.read_file(INDEX_GPKG, layer=INDEX_LAYER)
    if gdf.crs is None:
        raise RuntimeError("district_index_v2.gpkg: у слоя нет CRS. Это надо чинить, иначе карта будет неверной.")
    gdf = gdf.to_crs(WGS84)

    if "index_score_0_1" not in gdf.columns:
        raise RuntimeError("В слое индекса нет колонки index_score_0_1.")

    # --- demand ---
    demand = load_gpkg_or_csv_points(DEMAND_GPKG, DEMAND_LAYER, DEMAND_CSV)
    demand = demand.to_crs(WGS84)
    if "demand_w" not in demand.columns:
        raise RuntimeError("В demand_points нет колонки demand_w.")

    # --- pvz selected ---
    pvz = load_gpkg_or_csv_points(PVZ_GPKG, PVZ_LAYER, PVZ_CSV)
    pvz = pvz.to_crs(WGS84)

    # центр карты
    b = gdf.total_bounds  # (minx, miny, maxx, maxy)
    center_lat = (b[1] + b[3]) / 2
    center_lon = (b[0] + b[2]) / 2

    m = folium.Map(location=[center_lat, center_lon], zoom_start=10, tiles="cartodbpositron")

    # --- слой полигонов индекса ---
    vmin = float(gdf["index_score_0_1"].min())
    vmax = float(gdf["index_score_0_1"].max())
    colormap = cm.linear.YlOrRd_09.scale(vmin, vmax)
    colormap.caption = "Index score (0..1)"
    colormap.add_to(m)

    def poly_style(feature):
        v = feature["properties"].get("index_score_0_1", None)
        try:
            v = float(v)
        except Exception:
            v = None
        return {
            "fillColor": colormap(v) if v is not None else "#cccccc",
            "color": "#333333",
            "weight": 1,
            "fillOpacity": 0.55,
        }

    tooltip_fields = []
    tooltip_aliases = []
    for col, alias in [
        ("district_name", "District"),
        ("index_rank", "Rank"),
        ("index_score_0_1", "Score"),
        ("res_buildings_density_km2", "Res bld density / km2"),
        ("walk_reach_nodes_10min_p50", "Walk reach p50"),
        ("metro_walk_time_s_p10", "Metro walk p10 (s)"),
        ("competitor_density_km2", "Competitors / km2"),
        ("dormitory_cnt", "Dorms cnt"),
        ("cemetery_area_share", "Cemetery share"),
    ]:
        if col in gdf.columns:
            tooltip_fields.append(col)
            tooltip_aliases.append(alias)

    folium.GeoJson(
        data=gdf,
        name="Index polygons",
        style_function=poly_style,
        tooltip=GeoJsonTooltip(
            fields=tooltip_fields,
            aliases=tooltip_aliases,
            localize=True,
            sticky=True,
        ),
    ).add_to(m)

    # --- heatmap спроса ---
    # чтобы браузер не умер: можно ограничить число точек
    demand_h = demand[["demand_w", "geometry"]].copy()
    demand_h["lat"] = demand_h.geometry.y.astype(float)
    demand_h["lon"] = demand_h.geometry.x.astype(float)
    demand_h["w"] = demand_h["demand_w"].astype(float)

    if MAX_HEAT_POINTS is not None and len(demand_h) > MAX_HEAT_POINTS:
        # берём самые “тяжёлые” точки, остальное отбрасываем
        demand_h = demand_h.sort_values("w", ascending=False).head(MAX_HEAT_POINTS)

    heat_data = demand_h[["lat", "lon", "w"]].values.tolist()

    folium.FeatureGroup(name="Demand heatmap", show=True).add_to(m)
    HeatMap(
        heat_data,
        name="Demand heatmap",
        radius=HEAT_RADIUS,
        blur=HEAT_BLUR,
        min_opacity=HEAT_MIN_OPACITY,
        max_zoom=12,
    ).add_to(m)

    # --- точки выбранных ПВЗ ---
    pvz_fg = folium.FeatureGroup(name="Selected PVZ (K=20)", show=True)
    pvz_fg.add_to(m)

    # поля из 06 (могут быть не все, если менял скрипт)
    for _, row in pvz.iterrows():
        lat = float(row.geometry.y)
        lon = float(row.geometry.x)

        sel_rank = row.get("sel_rank", None)
        gain = row.get("gain_demand_w", None)
        share = row.get("covered_cum_share", None)
        dist_name = row.get("district_name", "")

        title_parts = []
        if sel_rank is not None and not (isinstance(sel_rank, float) and math.isnan(sel_rank)):
            title_parts.append(f"rank={int(sel_rank)}")
        if dist_name:
            title_parts.append(str(dist_name))
        if gain is not None and not (isinstance(gain, float) and math.isnan(gain)):
            title_parts.append(f"gain={int(gain)}")
        if share is not None and not (isinstance(share, float) and math.isnan(share)):
            title_parts.append(f"cum_share={float(share):.3f}")

        popup = folium.Popup("<br>".join(title_parts) if title_parts else "PVZ", max_width=300)

        folium.CircleMarker(
            location=[lat, lon],
            radius=PVZ_RADIUS,
            weight=2,
            fill=True,
            fill_opacity=0.9,
            popup=popup,
        ).add_to(pvz_fg)

    folium.LayerControl(collapsed=False).add_to(m)

    m.save(str(OUT_HTML))
    print("DONE:", OUT_HTML)


if __name__ == "__main__":
    main()
