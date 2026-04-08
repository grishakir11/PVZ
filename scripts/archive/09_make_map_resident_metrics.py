# 09_make_map_resident_metrics.py
# HTML-карта по метрикам "спрос жителей + удобство жителям до ближайшего ПВЗ".
#
# Вход:
#   - pvz_project/district_resident_metrics.gpkg (layer: district_resident_metrics)
#   - pvz_project/pvz_selected_20.gpkg (layer: pvz_selected_20)
# Выход:
#   - pvz_project/map_resident_metrics_pvz20.html

from pathlib import Path
import math

import geopandas as gpd
import folium
from folium.features import GeoJsonTooltip
import branca.colormap as cm


PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

METRICS_GPKG = PROJECT_DIR / "district_resident_metrics.gpkg"
METRICS_LAYER = "district_resident_metrics"

PVZ_GPKG = PROJECT_DIR / "pvz_selected_20.gpkg"
PVZ_LAYER = "pvz_selected_20"

OUT_HTML = PROJECT_DIR / "map_resident_metrics_pvz20.html"

WGS84 = "EPSG:4326"


def tooltip_for(gdf, pairs):
    fields = [c for c, _ in pairs if c in gdf.columns]
    aliases = [a for c, a in pairs if c in gdf.columns]
    return GeoJsonTooltip(fields=fields, aliases=aliases, localize=True, sticky=True)


def safe_log1p(x):
    try:
        x = float(x)
        if not math.isfinite(x) or x < 0:
            return None
        return math.log1p(x)
    except Exception:
        return None


def main():
    gdf = gpd.read_file(METRICS_GPKG, layer=METRICS_LAYER)
    if gdf.crs is None:
        raise RuntimeError("district_resident_metrics.gpkg: у слоя нет CRS.")
    gdf = gdf.to_crs(WGS84)

    for col in ["district_name", "demand_total", "share_10min"]:
        if col not in gdf.columns:
            raise RuntimeError(f"В district_resident_metrics нет колонки {col}.")

    # центр карты
    b = gdf.total_bounds
    center_lat = (b[1] + b[3]) / 2
    center_lon = (b[0] + b[2]) / 2

    m = folium.Map(location=[center_lat, center_lon], zoom_start=10, tiles="cartodbpositron")

    # ---------- Layer A: demand_total (log scale) ----------
    gdf["demand_log"] = gdf["demand_total"].apply(safe_log1p)

    v = gdf["demand_log"].dropna()
    vmin = float(v.min()) if len(v) else 0.0
    vmax = float(v.max()) if len(v) else 1.0

    cmap_demand = cm.linear.YlOrRd_09.scale(vmin, vmax)
    cmap_demand.caption = "Demand (log1p of demand_total)"
    cmap_demand.add_to(m)

    def style_demand(feature):
        val = feature["properties"].get("demand_log", None)
        try:
            val = float(val)
        except Exception:
            val = None
        return {
            "fillColor": cmap_demand(val) if val is not None else "#cccccc",
            "color": "#333333",
            "weight": 1,
            "fillOpacity": 0.55,
        }

    demand_tooltip = tooltip_for(gdf, [
        ("district_name", "District"),
        ("demand_total", "Demand total"),
        ("share_10min", "Share <=10 min"),
        ("p50_time_min", "P50 time (min)"),
        ("mean_time_min", "Mean time (min)"),
    ])

    folium.GeoJson(
        data=gdf,
        name="Demand total (log scale)",
        style_function=style_demand,
        tooltip=demand_tooltip,
        show=False,
    ).add_to(m)

    # ---------- Layer B: convenience share_10min ----------
    cmap_share = cm.linear.YlGn_09.scale(0.0, 1.0)
    cmap_share.caption = "Convenience: share of demand within 10 min"
    cmap_share.add_to(m)

    def style_share(feature):
        val = feature["properties"].get("share_10min", None)
        try:
            val = float(val)
        except Exception:
            val = None
        return {
            "fillColor": cmap_share(val) if val is not None else "#cccccc",
            "color": "#333333",
            "weight": 1,
            "fillOpacity": 0.55,
        }

    conv_tooltip = tooltip_for(gdf, [
        ("district_name", "District"),
        ("share_10min", "Share <=10 min"),
        ("p50_time_min", "P50 time (min)"),
        ("p90_time_min", "P90 time (min)"),
        ("demand_total", "Demand total"),
    ])

    folium.GeoJson(
        data=gdf,
        name="Convenience (share <=10 min)",
        style_function=style_share,
        tooltip=conv_tooltip,
        show=True,
    ).add_to(m)

    # ---------- PVZ points ----------
    pvz = gpd.read_file(PVZ_GPKG, layer=PVZ_LAYER)
    if pvz.crs is None:
        raise RuntimeError("pvz_selected_20.gpkg: у слоя нет CRS.")
    pvz = pvz.to_crs(WGS84)

    fg = folium.FeatureGroup(name="Selected PVZ (K=20)", show=True)
    fg.add_to(m)

    for _, row in pvz.iterrows():
        lat = float(row.geometry.y)
        lon = float(row.geometry.x)

        parts = []
        sel_rank = row.get("sel_rank", None)
        gain = row.get("gain_demand_w", None)
        cum_share = row.get("covered_cum_share", None)
        dist_name = row.get("district_name", None)

        if sel_rank is not None and not (isinstance(sel_rank, float) and math.isnan(sel_rank)):
            parts.append(f"rank={int(sel_rank)}")
        if dist_name:
            parts.append(str(dist_name))
        if gain is not None and not (isinstance(gain, float) and math.isnan(gain)):
            parts.append(f"gain={int(gain)}")
        if cum_share is not None and not (isinstance(cum_share, float) and math.isnan(cum_share)):
            parts.append(f"cum_share={float(cum_share):.3f}")

        popup = folium.Popup("<br>".join(parts) if parts else "PVZ", max_width=260)

        folium.CircleMarker(
            location=[lat, lon],
            radius=6,
            weight=2,
            fill=True,
            fill_opacity=0.9,
            popup=popup,
        ).add_to(fg)

    folium.LayerControl(collapsed=False).add_to(m)

    m.save(str(OUT_HTML))
    print("DONE:", OUT_HTML)


if __name__ == "__main__":
    main()
