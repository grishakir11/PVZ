# 17_compare_k20_baseline_vs_mean.py
# Сравнение двух решений при K=20:
# 1) первые 20 из pvz_selected_kmax.csv (охват 10 минут)
# 2) pvz_selected_mean_k20.csv (минимизация среднего времени)
#
# Считает по районам метрики "от дома":
# - доля спроса <=10 и <=15 минут
# - среднее / медиана / p90 времени
# И строит две PNG-карты:
# - разница среднего времени (мин)
# - разница доли <=10 минут
#
# Вход:
#   - pvz_project/demand_points.gpkg (layer: demand_points)   (district_name, demand_w)
#   - pvz_project/pvz_selected_kmax.csv                       (sel_rank, lat, lon)
#   - pvz_project/pvz_selected_mean_k20.csv                   (sel_rank, lat, lon)
#   - pvz_project/district_index_v2.gpkg (layer: districts_index_v2) (district_name + геометрия)
#   - moscow_walk.graphml
#
# Выход:
#   - pvz_project/compare_k20_by_district.csv
#   - pvz_project/map_delta_mean_time_k20_baseline_vs_mean.png
#   - pvz_project/map_delta_share10_k20_baseline_vs_mean.png
#   - pvz_project/map_points_k20_baseline_vs_mean.png

from pathlib import Path
import math
import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
import osmnx as ox
import matplotlib.pyplot as plt

PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

DEMAND_GPKG = PROJECT_DIR / "demand_points.gpkg"
DEMAND_LAYER = "demand_points"

PVZ_RANKED_CSV = PROJECT_DIR / "pvz_selected_kmax.csv"
PVZ_MEAN_CSV = PROJECT_DIR / "pvz_selected_mean_k20.csv"

POLY_GPKG = PROJECT_DIR / "district_index_v2.gpkg"
POLY_LAYER = "districts_index_v2"

GRAPHML = Path(r"C:\Users\sgs-w\Downloads\moscow_walk.graphml")

OUT_CSV = PROJECT_DIR / "compare_k20_by_district.csv"
OUT_PNG_MEAN = PROJECT_DIR / "map_delta_mean_time_k20_baseline_vs_mean.png"
OUT_PNG_SHARE10 = PROJECT_DIR / "map_delta_share10_k20_baseline_vs_mean.png"
OUT_PNG_POINTS = PROJECT_DIR / "map_points_k20_baseline_vs_mean.png"

WGS84 = "EPSG:4326"
METRIC_CRS = "EPSG:32637"

K = 20

# потолок для расчёта (минуты дальше потолка считаются как потолок)
MAX_TIME_S = 10800  # 180 минут

# если в графе нет walk_time_s
WALK_SPEED_MPS = 1.3


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


def metrics(times_min, weights):
    t = np.asarray(times_min, dtype=float)
    w = np.asarray(weights, dtype=float)
    m = np.isfinite(t) & np.isfinite(w) & (w > 0)
    if m.sum() == 0:
        return None

    t = t[m]
    w = w[m]
    wsum = float(w.sum())

    out = {}
    out["demand_total"] = wsum
    out["share_10min"] = float(w[t <= 10].sum() / wsum)
    out["share_15min"] = float(w[t <= 15].sum() / wsum)
    out["mean_time_min"] = float((t * w).sum() / wsum)
    out["p50_time_min"] = weighted_quantile(t, w, 0.50)
    out["p90_time_min"] = weighted_quantile(t, w, 0.90)
    return out


def times_to_nearest_pvz(Gu, demand_nodes, pvz_nodes):
    dist = nx.multi_source_dijkstra_path_length(
        Gu, sources=pvz_nodes, weight="walk_time_s", cutoff=MAX_TIME_S
    )
    t_sec = np.array([float(dist.get(int(n), MAX_TIME_S)) for n in demand_nodes], dtype=float)
    t_sec = np.minimum(t_sec, float(MAX_TIME_S))
    return t_sec / 60.0


def main():
    # спрос
    demand = gpd.read_file(DEMAND_GPKG, layer=DEMAND_LAYER)
    if demand.crs is None:
        demand = demand.set_crs(METRIC_CRS, allow_override=True)
    if "district_name" not in demand.columns or "demand_w" not in demand.columns:
        raise RuntimeError("В demand_points должны быть district_name и demand_w.")
    demand_wgs = demand.to_crs(WGS84)

    # граф
    G = load_graphml_robust(GRAPHML)
    G = ensure_walk_time(G)
    Gu = to_undirected_compat(G)

    # привязка спроса к узлам
    demand_nodes = nearest_nodes_compat(Gu, X=demand_wgs.geometry.x.values, Y=demand_wgs.geometry.y.values)
    demand_nodes = np.array([int(x) for x in demand_nodes], dtype=np.int64)

    # два набора ПВЗ
    pvz_ranked = pd.read_csv(PVZ_RANKED_CSV, encoding="utf-8-sig").sort_values("sel_rank").reset_index(drop=True)
    pvz_base = pvz_ranked.head(K).copy()

    pvz_mean = pd.read_csv(PVZ_MEAN_CSV, encoding="utf-8-sig").sort_values("sel_rank").reset_index(drop=True)
    pvz_mean = pvz_mean.head(K).copy()

    pvz_base_gdf = gpd.GeoDataFrame(pvz_base, geometry=gpd.points_from_xy(pvz_base["lon"], pvz_base["lat"], crs=WGS84))
    pvz_mean_gdf = gpd.GeoDataFrame(pvz_mean, geometry=gpd.points_from_xy(pvz_mean["lon"], pvz_mean["lat"], crs=WGS84))

    pvz_base_nodes = nearest_nodes_compat(Gu, X=pvz_base_gdf.geometry.x.values, Y=pvz_base_gdf.geometry.y.values)
    pvz_mean_nodes = nearest_nodes_compat(Gu, X=pvz_mean_gdf.geometry.x.values, Y=pvz_mean_gdf.geometry.y.values)

    pvz_base_nodes = list(set(int(x) for x in pvz_base_nodes))
    pvz_mean_nodes = list(set(int(x) for x in pvz_mean_nodes))

    # времена
    t_base = times_to_nearest_pvz(Gu, demand_nodes, pvz_base_nodes)
    t_mean = times_to_nearest_pvz(Gu, demand_nodes, pvz_mean_nodes)

    df = pd.DataFrame({
        "district_name": demand["district_name"].astype(str).values,
        "demand_w": demand["demand_w"].astype(float).values,
        "t_base": t_base,
        "t_mean": t_mean,
    })

    rows = []
    for name, g in df.groupby("district_name", sort=False):
        w = g["demand_w"].values
        mb = metrics(g["t_base"].values, w)
        mm = metrics(g["t_mean"].values, w)
        if mb is None or mm is None:
            continue

        row = {"district_name": name}
        for k, v in mb.items():
            row[f"{k}_base"] = v
        for k, v in mm.items():
            row[f"{k}_mean"] = v

        row["delta_share_10min"] = row["share_10min_mean"] - row["share_10min_base"]
        row["delta_share_15min"] = row["share_15min_mean"] - row["share_15min_base"]
        row["delta_mean_time_min"] = row["mean_time_min_mean"] - row["mean_time_min_base"]
        row["delta_p50_time_min"] = row["p50_time_min_mean"] - row["p50_time_min_base"]
        row["delta_p90_time_min"] = row["p90_time_min_mean"] - row["p90_time_min_base"]
        rows.append(row)

    out = pd.DataFrame(rows)
    out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    # полигоны + карты
    polys = gpd.read_file(POLY_GPKG, layer=POLY_LAYER)
    if polys.crs is None:
        polys = polys.set_crs(METRIC_CRS, allow_override=True)
    polys = polys.to_crs(WGS84)

    if "district_name" not in polys.columns:
        raise RuntimeError("В полигонах нет district_name.")

    gmap = polys.merge(out, on="district_name", how="left")

    # 1) карта: разница среднего времени (отрицательная = лучше для mean-решения)
    plt.figure(figsize=(10, 10))
    ax = plt.gca()
    gmap.plot(column="delta_mean_time_min", ax=ax, legend=True, missing_kwds={"color": "#cccccc"})
    ax.set_title("Разница среднего времени (мин): (минимизация среднего) − (охват 10 мин)")
    ax.set_axis_off()
    plt.tight_layout()
    plt.savefig(OUT_PNG_MEAN, dpi=220)

    # 2) карта: разница доли <=10 минут (положительная = лучше по порогу 10 минут)
    plt.figure(figsize=(10, 10))
    ax = plt.gca()
    gmap.plot(column="delta_share_10min", ax=ax, legend=True, missing_kwds={"color": "#cccccc"})
    ax.set_title("Разница доли спроса ≤10 мин: (минимизация среднего) − (охват 10 мин)")
    ax.set_axis_off()
    plt.tight_layout()
    plt.savefig(OUT_PNG_SHARE10, dpi=220)

    # 3) карта точек двух решений (просто наложение)
    plt.figure(figsize=(10, 10))
    ax = plt.gca()
    polys.plot(ax=ax)
    pvz_base_gdf.plot(ax=ax, markersize=12)
    pvz_mean_gdf.plot(ax=ax, markersize=12)
    ax.set_title("Две сети K=20: точки (охват 10 мин) и (минимизация среднего времени)")
    ax.set_axis_off()
    plt.tight_layout()
    plt.savefig(OUT_PNG_POINTS, dpi=220)

    print("ГОТОВО")
    print("CSV :", OUT_CSV)
    print("PNG :", OUT_PNG_MEAN)
    print("PNG :", OUT_PNG_SHARE10)
    print("PNG :", OUT_PNG_POINTS)


if __name__ == "__main__":
    main()