# 14_delta_k20_k30_by_district_and_map.py
# Делает анализ улучшения сервиса "от дома до ПВЗ" при переходе K0 -> K1:
# - по каждой территории: спрос, доли в 10/15 мин, среднее/медиана/90-й процентиль времени, эффективный спрос D
# - разницы (K1 - K0)
# - HTML-карта разниц + точки добавленных ПВЗ
#
# Вход:
#   - pvz_project/demand_points.gpkg (layer: demand_points)  (district_name, demand_w)
#   - pvz_project/pvz_selected_kmax.csv (sel_rank, lat, lon)
#   - moscow_walk.graphml
#   - pvz_project/district_index_v2.gpkg (layer: districts_index_v2)  (только геометрия + district_name) для карты
#
# Выход:
#   - pvz_project/delta_k20_k30_by_district.csv
#   - pvz_project/pvz_added_k20_to_k30.csv
#   - pvz_project/map_delta_k20_k30.html

from pathlib import Path
import math
import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
import osmnx as ox
import folium
from folium.features import GeoJsonTooltip
import branca.colormap as cm


# ====== НАСТРОЙКИ ======
PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

DEMAND_GPKG = PROJECT_DIR / "demand_points.gpkg"
DEMAND_LAYER = "demand_points"

PVZ_RANKED_CSV = PROJECT_DIR / "pvz_selected_kmax.csv"

GRAPHML = Path(r"C:\Users\sgs-w\Downloads\moscow_walk.graphml")

# Полигоны для карты (если у тебя другой файл с границами — поменяй тут)
POLY_GPKG = PROJECT_DIR / "district_index_v2.gpkg"
POLY_LAYER = "districts_index_v2"

OUT_CSV = PROJECT_DIR / "delta_k20_k30_by_district.csv"
OUT_PVZ_ADDED = PROJECT_DIR / "pvz_added_k20_to_k30.csv"
OUT_HTML = PROJECT_DIR / "map_delta_k20_k30.html"

WGS84 = "EPSG:4326"
METRIC_CRS = "EPSG:32637"

K0 = 20
K1 = 30

# пороги времени (мин)
T_LIST_MIN = [10, 15]

# если граф без walk_time_s
WALK_SPEED_MPS = 1.3

# ограничение для поиска (чтобы не бегать бесконечно)
MAX_TIME_S = 10800  # 180 минут
# =======================


def f_time_minutes(t_min: np.ndarray) -> np.ndarray:
    """Сценарная функция предпочтения: чем дальше идти, тем ниже 'конверсия'."""
    t = np.asarray(t_min, dtype=float)
    out = np.zeros_like(t, dtype=float)

    m = t <= 10
    out[m] = 1.00

    m = (t > 10) & (t <= 20)
    out[m] = 0.85

    m = (t > 20) & (t <= 30)
    out[m] = 0.70

    m = (t > 30) & (t <= 45)
    out[m] = 0.50

    m = (t > 45) & (t <= 60)
    out[m] = 0.35

    m = t > 60
    out[m] = 0.20

    return out


def _iter_edges(G):
    if isinstance(G, (nx.MultiGraph, nx.MultiDiGraph)):
        for u, v, k, data in G.edges(keys=True, data=True):
            yield u, v, k, data
    else:
        for u, v, data in G.edges(data=True):
            yield u, v, None, data


def load_graphml_robust(path: Path):
    try:
        return ox.load_graphml(path)
    except Exception:
        G = nx.read_graphml(path)

        mapping = {}
        for n in list(G.nodes):
            if isinstance(n, str):
                try:
                    mapping[n] = int(n)
                except Exception:
                    pass
        if mapping:
            G = nx.relabel_nodes(G, mapping, copy=True)

        if "crs" not in G.graph:
            G.graph["crs"] = "epsg:4326"

        for n, data in G.nodes(data=True):
            if "x" in data:
                try: data["x"] = float(data["x"])
                except Exception: pass
            if "y" in data:
                try: data["y"] = float(data["y"])
                except Exception: pass

        for _, _, _, data in _iter_edges(G):
            if "length" in data:
                try: data["length"] = float(data["length"])
                except Exception: pass
            if "walk_time_s" in data:
                try: data["walk_time_s"] = float(data["walk_time_s"])
                except Exception: pass
            if "oneway" in data and isinstance(data["oneway"], str):
                s = data["oneway"].strip().lower()
                if s in ("yes", "true", "1"):
                    data["oneway"] = True
                elif s in ("no", "false", "0"):
                    data["oneway"] = False

        return G


def add_edge_lengths_compat(G):
    try:
        import osmnx.distance as od
        return od.add_edge_lengths(G)
    except Exception:
        pass
    if hasattr(ox, "add_edge_lengths"):
        return ox.add_edge_lengths(G)
    raise AttributeError("Не найден add_edge_lengths.")


def ensure_walk_time(G):
    any_edge = None
    for _, _, _, data in _iter_edges(G):
        any_edge = data
        break
    if any_edge is None:
        raise RuntimeError("Граф пустой.")

    if "walk_time_s" in any_edge:
        for _, _, _, data in _iter_edges(G):
            if "walk_time_s" in data:
                try: data["walk_time_s"] = float(data["walk_time_s"])
                except Exception: pass
        return G

    G = add_edge_lengths_compat(G)
    for _, _, _, data in _iter_edges(G):
        if "length" in data:
            data["walk_time_s"] = float(data["length"]) / WALK_SPEED_MPS
    return G


def to_undirected_compat(G):
    try:
        return ox.convert.to_undirected(G)
    except Exception:
        return G.to_undirected()


def nearest_nodes_compat(G, X, Y):
    try:
        import osmnx.distance as od
        return od.nearest_nodes(G, X=X, Y=Y)
    except Exception:
        pass
    if hasattr(ox, "distance") and hasattr(ox.distance, "nearest_nodes"):
        return ox.distance.nearest_nodes(G, X=X, Y=Y)
    if hasattr(ox, "nearest_nodes"):
        return ox.nearest_nodes(G, X=X, Y=Y)
    raise AttributeError("Не найден nearest_nodes.")


def weighted_quantile(values, weights, q):
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    m = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if m.sum() == 0:
        return np.nan
    v = values[m]
    w = weights[m]
    idx = np.argsort(v)
    v = v[idx]
    w = w[idx]
    cw = np.cumsum(w)
    cut = q * cw[-1]
    return float(v[np.searchsorted(cw, cut, side="left")])


def metrics_for_times(times_min: np.ndarray, weights: np.ndarray):
    t = np.asarray(times_min, dtype=float)
    w = np.asarray(weights, dtype=float)
    m = np.isfinite(t) & np.isfinite(w) & (w > 0)
    if m.sum() == 0:
        return {}

    t = t[m]
    w = w[m]
    wsum = float(w.sum())

    out = {}
    out["mean_time_min"] = float((t * w).sum() / wsum)
    out["p50_time_min"] = weighted_quantile(t, w, 0.50)
    out["p90_time_min"] = weighted_quantile(t, w, 0.90)

    for T in T_LIST_MIN:
        out[f"share_{T}min"] = float(w[t <= T].sum() / wsum)

    conv = f_time_minutes(t)
    out["D_effective"] = float((w * conv).sum())
    out["D_effective_share"] = float(out["D_effective"] / wsum)

    out["demand_total"] = float(wsum)
    return out


def compute_times_to_pvz(Gu, demand_nodes: np.ndarray, pvz_nodes: list[int]):
    dist = nx.multi_source_dijkstra_path_length(Gu, sources=pvz_nodes, weight="walk_time_s", cutoff=MAX_TIME_S)
    t_sec = np.array([float(dist.get(int(n), MAX_TIME_S)) for n in demand_nodes], dtype=float)
    return t_sec / 60.0


def main():
    # 1) спрос
    demand = gpd.read_file(DEMAND_GPKG, layer=DEMAND_LAYER)
    if demand.crs is None:
        demand = demand.set_crs(METRIC_CRS, allow_override=True)
    if "district_name" not in demand.columns or "demand_w" not in demand.columns:
        raise RuntimeError("В demand_points должны быть district_name и demand_w.")
    demand_wgs = demand.to_crs(WGS84)

    # 2) ПВЗ ранжированные
    pvz = pd.read_csv(PVZ_RANKED_CSV, encoding="utf-8-sig").sort_values("sel_rank").reset_index(drop=True)
    if max(K0, K1) > int(pvz["sel_rank"].max()):
        raise RuntimeError("K0/K1 больше чем kmax в pvz_selected_kmax.csv")

    pvz_k0 = pvz.head(K0).copy()
    pvz_k1 = pvz.head(K1).copy()
    pvz_added = pvz.iloc[K0:K1].copy()
    pvz_added.to_csv(OUT_PVZ_ADDED, index=False, encoding="utf-8-sig")

    # 3) граф
    G = load_graphml_robust(GRAPHML)
    G = ensure_walk_time(G)
    Gu = to_undirected_compat(G)

    # 4) привязка спроса и ПВЗ к узлам графа
    demand_nodes = nearest_nodes_compat(Gu, X=demand_wgs.geometry.x.values, Y=demand_wgs.geometry.y.values)
    demand_nodes = np.array([int(x) for x in demand_nodes], dtype=np.int64)

    pvz0_gdf = gpd.GeoDataFrame(pvz_k0, geometry=gpd.points_from_xy(pvz_k0["lon"], pvz_k0["lat"], crs=WGS84))
    pvz1_gdf = gpd.GeoDataFrame(pvz_k1, geometry=gpd.points_from_xy(pvz_k1["lon"], pvz_k1["lat"], crs=WGS84))
    pvzA_gdf = gpd.GeoDataFrame(pvz_added, geometry=gpd.points_from_xy(pvz_added["lon"], pvz_added["lat"], crs=WGS84))

    pvz_nodes_k0 = [int(x) for x in nearest_nodes_compat(Gu, X=pvz0_gdf.geometry.x.values, Y=pvz0_gdf.geometry.y.values)]
    pvz_nodes_k1 = [int(x) for x in nearest_nodes_compat(Gu, X=pvz1_gdf.geometry.x.values, Y=pvz1_gdf.geometry.y.values)]
    pvz_nodes_add = [int(x) for x in nearest_nodes_compat(Gu, X=pvzA_gdf.geometry.x.values, Y=pvzA_gdf.geometry.y.values)]

    pvz_nodes_k0 = list(set(pvz_nodes_k0))
    pvz_nodes_k1 = list(set(pvz_nodes_k1))
    pvz_nodes_add = list(set(pvz_nodes_add))

    # 5) времена до ближайшего ПВЗ для K0/K1
    t0_min = compute_times_to_pvz(Gu, demand_nodes, pvz_nodes_k0)
    t1_min = compute_times_to_pvz(Gu, demand_nodes, pvz_nodes_k1)

    # 6) агрегация по территориям
    df = pd.DataFrame({
        "district_name": demand["district_name"].astype(str).values,
        "demand_w": demand["demand_w"].astype(float).values,
        "t0_min": t0_min,
        "t1_min": t1_min,
    })

    rows = []
    for name, g in df.groupby("district_name", sort=False):
        w = g["demand_w"].values
        m0 = metrics_for_times(g["t0_min"].values, w)
        m1 = metrics_for_times(g["t1_min"].values, w)

        row = {"district_name": name}
        # K0
        for k, v in m0.items():
            row[f"{k}_k{K0}"] = v
        # K1
        for k, v in m1.items():
            row[f"{k}_k{K1}"] = v
        # delta
        row[f"delta_mean_time_min"] = row[f"mean_time_min_k{K1}"] - row[f"mean_time_min_k{K0}"]
        row[f"delta_p50_time_min"] = row[f"p50_time_min_k{K1}"] - row[f"p50_time_min_k{K0}"]
        row[f"delta_p90_time_min"] = row[f"p90_time_min_k{K1}"] - row[f"p90_time_min_k{K0}"]
        for T in T_LIST_MIN:
            row[f"delta_share_{T}min"] = row[f"share_{T}min_k{K1}"] - row[f"share_{T}min_k{K0}"]
        row["delta_D_effective"] = row[f"D_effective_k{K1}"] - row[f"D_effective_k{K0}"]
        rows.append(row)

    out = pd.DataFrame(rows)
    out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    # 7) карта
    polys = gpd.read_file(POLY_GPKG, layer=POLY_LAYER)
    if polys.crs is None:
        polys = polys.set_crs(METRIC_CRS, allow_override=True)
    polys = polys.to_crs(WGS84)

    if "district_name" not in polys.columns:
        raise RuntimeError("В полигонах нет district_name. Надо выбрать другой слой границ.")

    m = polys.merge(out, on="district_name", how="left")

    b = m.total_bounds
    center_lat = (b[1] + b[3]) / 2
    center_lon = (b[0] + b[2]) / 2
    mp = folium.Map(location=[center_lat, center_lon], zoom_start=10, tiles="cartodbpositron")

    # слой 1: прирост доли в 10 мин (0..1)
    v = m["delta_share_10min"].dropna()
    vmin = float(v.min()) if len(v) else 0.0
    vmax = float(v.max()) if len(v) else 1.0
    cmap = cm.linear.YlGn_09.scale(vmin, vmax)
    cmap.caption = f"Δ доля спроса в 10 мин (K={K0}->{K1})"
    cmap.add_to(mp)

    def style_delta_share(feature):
        val = feature["properties"].get("delta_share_10min", None)
        try:
            val = float(val)
        except Exception:
            val = None
        return {
            "fillColor": cmap(val) if val is not None else "#cccccc",
            "color": "#333333",
            "weight": 1,
            "fillOpacity": 0.55,
        }

    tooltip = GeoJsonTooltip(
        fields=[c for c in [
            "district_name",
            "demand_total_k20",
            "share_10min_k20",
            "share_10min_k30",
            "delta_share_10min",
            "p50_time_min_k20",
            "p50_time_min_k30",
            "delta_p50_time_min",
        ] if c in m.columns],
        aliases=[
            "Территория",
            f"Спрос (K={K0})",
            f"Доля<=10 мин (K={K0})",
            f"Доля<=10 мин (K={K1})",
            "Δ доли<=10 мин",
            f"Медиана (K={K0}), мин",
            f"Медиана (K={K1}), мин",
            "Δ медианы, мин",
        ],
        localize=True,
        sticky=True,
    )

    folium.GeoJson(
        data=m,
        name="Δ доли в 10 мин",
        style_function=style_delta_share,
        tooltip=tooltip,
        show=True,
    ).add_to(mp)

    # слой 2: изменение среднего времени (обычно отрицательное = стало лучше)
    v2 = m["delta_mean_time_min"].dropna()
    vmin2 = float(v2.min()) if len(v2) else -1.0
    vmax2 = float(v2.max()) if len(v2) else 1.0
    cmap2 = cm.linear.RdYlGn_11.scale(vmin2, vmax2)
    cmap2.caption = f"Δ среднее время, мин (K={K0}->{K1}), отрицательное = улучшение"
    cmap2.add_to(mp)

    def style_delta_mean(feature):
        val = feature["properties"].get("delta_mean_time_min", None)
        try:
            val = float(val)
        except Exception:
            val = None
        return {
            "fillColor": cmap2(val) if val is not None else "#cccccc",
            "color": "#333333",
            "weight": 1,
            "fillOpacity": 0.55,
        }

    folium.GeoJson(
        data=m,
        name="Δ среднего времени",
        style_function=style_delta_mean,
        tooltip=tooltip,
        show=False,
    ).add_to(mp)

    # точки: старые K0 и добавленные (K0+1..K1)
    fg0 = folium.FeatureGroup(name=f"ПВЗ (первые {K0})", show=False)
    fgA = folium.FeatureGroup(name=f"Добавленные ПВЗ ({K0+1}..{K1})", show=True)
    fg0.add_to(mp)
    fgA.add_to(mp)

    for _, r in pvz0_gdf.iterrows():
        folium.CircleMarker(
            location=[float(r.geometry.y), float(r.geometry.x)],
            radius=4, weight=1, fill=True, fill_opacity=0.6,
            popup=f"K0 rank={int(r['sel_rank'])}" if "sel_rank" in r else "PVZ",
        ).add_to(fg0)

    for _, r in pvzA_gdf.iterrows():
        folium.CircleMarker(
            location=[float(r.geometry.y), float(r.geometry.x)],
            radius=6, weight=2, fill=True, fill_opacity=0.9,
            popup=f"ADDED rank={int(r['sel_rank'])}" if "sel_rank" in r else "PVZ added",
        ).add_to(fgA)

    folium.LayerControl(collapsed=False).add_to(mp)
    mp.save(str(OUT_HTML))

    print("ГОТОВО")
    print("CSV:", OUT_CSV)
    print("PVZ added:", OUT_PVZ_ADDED)
    print("MAP:", OUT_HTML)


if __name__ == "__main__":
    main()