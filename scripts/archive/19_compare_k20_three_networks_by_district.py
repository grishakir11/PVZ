# 19_compare_k20_three_networks_by_district.py
# Сравнение трёх сетей K=20 по районам и PNG-карты разницы относительно baseline:
# 1) baseline_coverage10: первые 20 точек из pvz_selected_kmax.csv
# 2) min_mean_time: pvz_selected_mean_k20.csv
# 3) max_effective_demand: pvz_selected_effective_k20.csv
#
# Метрики по району (взвешенно по demand_w):
# - доля спроса <=10 и <=15 минут
# - среднее / медиана / p90 времени
#
# Выход:
# - pvz_project/compare_k20_three_by_district.csv
# - pvz_project/map_delta_mean_time_min_mean_vs_base.png
# - pvz_project/map_delta_mean_time_effective_vs_base.png
# - pvz_project/map_delta_share10_min_mean_vs_base.png
# - pvz_project/map_delta_share10_effective_vs_base.png
# - pvz_project/map_points_k20_three.png

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
PVZ_EFF_CSV = PROJECT_DIR / "pvz_selected_effective_k20.csv"

POLY_GPKG = PROJECT_DIR / "district_index_v2.gpkg"
POLY_LAYER = "districts_index_v2"

GRAPHML = Path(r"C:\Users\sgs-w\Downloads\moscow_walk.graphml")

OUT_CSV = PROJECT_DIR / "compare_k20_three_by_district.csv"
OUT_PNG_MEAN_MEAN = PROJECT_DIR / "map_delta_mean_time_min_mean_vs_base.png"
OUT_PNG_MEAN_EFF = PROJECT_DIR / "map_delta_mean_time_effective_vs_base.png"
OUT_PNG_SHARE_MEAN = PROJECT_DIR / "map_delta_share10_min_mean_vs_base.png"
OUT_PNG_SHARE_EFF = PROJECT_DIR / "map_delta_share10_effective_vs_base.png"
OUT_PNG_POINTS = PROJECT_DIR / "map_points_k20_three.png"

WGS84 = "EPSG:4326"
METRIC_CRS = "EPSG:32637"

K = 20
MAX_TIME_S = 10800  # 180 минут
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


def load_points(csv_path: Path, k: int, ranked: bool) -> gpd.GeoDataFrame:
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    if ranked and "sel_rank" in df.columns:
        df = df.sort_values("sel_rank")
    df = df.head(k).copy()
    if not {"lat", "lon"}.issubset(df.columns):
        raise RuntimeError(f"{csv_path} должен иметь lat/lon")
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["lon"], df["lat"]), crs=WGS84)


def times_to_nearest(Gu, demand_nodes, pvz_nodes):
    dist = nx.multi_source_dijkstra_path_length(
        Gu, sources=pvz_nodes, weight="walk_time_s", cutoff=MAX_TIME_S
    )
    t_sec = np.array([float(dist.get(int(n), MAX_TIME_S)) for n in demand_nodes], dtype=float)
    t_sec = np.minimum(t_sec, float(MAX_TIME_S))
    return t_sec / 60.0


def main():
    # demand
    demand = gpd.read_file(DEMAND_GPKG, layer=DEMAND_LAYER)
    if demand.crs is None:
        demand = demand.set_crs(METRIC_CRS, allow_override=True)
    if "district_name" not in demand.columns or "demand_w" not in demand.columns:
        raise RuntimeError("В demand_points должны быть district_name и demand_w.")
    demand_wgs = demand.to_crs(WGS84)

    # graph
    G = load_graphml_robust(GRAPHML)
    G = ensure_walk_time(G)
    Gu = to_undirected_compat(G)

    # snap demand
    demand_nodes = nearest_nodes_compat(Gu, X=demand_wgs.geometry.x.values, Y=demand_wgs.geometry.y.values)
    demand_nodes = np.array([int(x) for x in demand_nodes], dtype=np.int64)

    # load pvz sets
    pvz_base = load_points(PVZ_RANKED_CSV, K, ranked=True)
    pvz_mean = load_points(PVZ_MEAN_CSV, K, ranked=True)
    pvz_eff = load_points(PVZ_EFF_CSV, K, ranked=True)

    pvz_base_nodes = list(set(int(x) for x in nearest_nodes_compat(Gu, X=pvz_base.geometry.x.values, Y=pvz_base.geometry.y.values)))
    pvz_mean_nodes = list(set(int(x) for x in nearest_nodes_compat(Gu, X=pvz_mean.geometry.x.values, Y=pvz_mean.geometry.y.values)))
    pvz_eff_nodes  = list(set(int(x) for x in nearest_nodes_compat(Gu, X=pvz_eff.geometry.x.values,  Y=pvz_eff.geometry.y.values)))

    # times for each demand point
    t_base = times_to_nearest(Gu, demand_nodes, pvz_base_nodes)
    t_mean = times_to_nearest(Gu, demand_nodes, pvz_mean_nodes)
    t_eff  = times_to_nearest(Gu, demand_nodes, pvz_eff_nodes)

    df = pd.DataFrame({
        "district_name": demand["district_name"].astype(str).values,
        "demand_w": demand["demand_w"].astype(float).values,
        "t_base": t_base,
        "t_mean": t_mean,
        "t_eff":  t_eff,
    })

    rows = []
    for name, g in df.groupby("district_name", sort=False):
        w = g["demand_w"].values

        mb = metrics(g["t_base"].values, w)
        mm = metrics(g["t_mean"].values, w)
        me = metrics(g["t_eff"].values, w)
        if mb is None or mm is None or me is None:
            continue

        row = {"district_name": name}
        for k, v in mb.items():
            row[f"{k}_base"] = v
        for k, v in mm.items():
            row[f"{k}_mean"] = v
        for k, v in me.items():
            row[f"{k}_eff"] = v

        row["delta_mean_minus_base"] = row["mean_time_min_mean"] - row["mean_time_min_base"]
        row["delta_eff_minus_base"]  = row["mean_time_min_eff"]  - row["mean_time_min_base"]

        row["delta_share10_mean_minus_base"] = row["share_10min_mean"] - row["share_10min_base"]
        row["delta_share10_eff_minus_base"]  = row["share_10min_eff"]  - row["share_10min_base"]

        rows.append(row)

    out = pd.DataFrame(rows)
    out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    # polygons for maps
    polys = gpd.read_file(POLY_GPKG, layer=POLY_LAYER)
    if polys.crs is None:
        polys = polys.set_crs(METRIC_CRS, allow_override=True)
    polys = polys.to_crs(WGS84)
    if "district_name" not in polys.columns:
        raise RuntimeError("В полигонах нет district_name.")

    gmap = polys.merge(out, on="district_name", how="left")

    # map 1: mean - base (отрицательное = лучше)
    plt.figure(figsize=(10, 10))
    ax = plt.gca()
    gmap.plot(column="delta_mean_minus_base", ax=ax, legend=True, missing_kwds={"color": "#cccccc"})
    ax.set_title("Δ среднего времени (мин): (минимизация среднего) − (baseline охват 10 мин)")
    ax.set_axis_off()
    plt.tight_layout()
    plt.savefig(OUT_PNG_MEAN_MEAN, dpi=220)

    # map 2: eff - base
    plt.figure(figsize=(10, 10))
    ax = plt.gca()
    gmap.plot(column="delta_eff_minus_base", ax=ax, legend=True, missing_kwds={"color": "#cccccc"})
    ax.set_title("Δ среднего времени (мин): (эффективный спрос) − (baseline охват 10 мин)")
    ax.set_axis_off()
    plt.tight_layout()
    plt.savefig(OUT_PNG_MEAN_EFF, dpi=220)

    # map 3: share10 mean - base
    plt.figure(figsize=(10, 10))
    ax = plt.gca()
    gmap.plot(column="delta_share10_mean_minus_base", ax=ax, legend=True, missing_kwds={"color": "#cccccc"})
    ax.set_title("Δ доли спроса ≤10 мин: (минимизация среднего) − (baseline охват 10 мин)")
    ax.set_axis_off()
    plt.tight_layout()
    plt.savefig(OUT_PNG_SHARE_MEAN, dpi=220)

    # map 4: share10 eff - base
    plt.figure(figsize=(10, 10))
    ax = plt.gca()
    gmap.plot(column="delta_share10_eff_minus_base", ax=ax, legend=True, missing_kwds={"color": "#cccccc"})
    ax.set_title("Δ доли спроса ≤10 мин: (эффективный спрос) − (baseline охват 10 мин)")
    ax.set_axis_off()
    plt.tight_layout()
    plt.savefig(OUT_PNG_SHARE_EFF, dpi=220)

    # points map: 3 sets
    plt.figure(figsize=(10, 10))
    ax = plt.gca()
    polys.plot(ax=ax, color="#f0f0f0", edgecolor="#999999", linewidth=0.3)

    pvz_base.plot(ax=ax, markersize=28, marker="o", label="baseline (охват 10 мин)")
    pvz_mean.plot(ax=ax, markersize=28, marker="^", label="минимизация среднего")
    pvz_eff.plot(ax=ax, markersize=28, marker="s", label="эффективный спрос")

    ax.set_title("Три сети K=20 (разные маркеры)")
    ax.set_axis_off()
    ax.legend(loc="lower left", frameon=True)
    plt.tight_layout()
    plt.savefig(OUT_PNG_POINTS, dpi=220)

    print("ГОТОВО")
    print("CSV:", OUT_CSV)
    print("PNG:", OUT_PNG_MEAN_MEAN)
    print("PNG:", OUT_PNG_MEAN_EFF)
    print("PNG:", OUT_PNG_SHARE_MEAN)
    print("PNG:", OUT_PNG_SHARE_EFF)
    print("PNG:", OUT_PNG_POINTS)


if __name__ == "__main__":
    main()