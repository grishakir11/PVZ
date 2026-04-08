# 21_compare_k20_four_networks_by_district.py
# Сравнение 4 сетей K=20 по районам и PNG-карты разницы относительно baseline:
# 1) baseline_coverage10: первые 20 точек из pvz_selected_kmax.csv
# 2) min_mean_time: pvz_selected_mean_k20.csv
# 3) max_effective_demand: pvz_selected_effective_k20.csv
# 4) effective_keep_zelenograd: pvz_selected_effective_keep_zelenograd_k20.csv
#
# Метрики по району (взвешенно по demand_w):
# - доля спроса <=10 и <=15 минут
# - среднее / медиана / p90 времени
#
# Выход:
# - pvz_project/compare_k20_four_by_district.csv
# - pvz_project/map_delta_mean_time_min_mean_vs_base.png
# - pvz_project/map_delta_mean_time_effective_vs_base.png
# - pvz_project/map_delta_mean_time_effective_keep_vs_base.png
# - pvz_project/map_delta_share10_min_mean_vs_base.png
# - pvz_project/map_delta_share10_effective_vs_base.png
# - pvz_project/map_delta_share10_effective_keep_vs_base.png
# - pvz_project/map_points_k20_four.png

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

PVZ_BASE_CSV = PROJECT_DIR / "pvz_selected_kmax.csv"
PVZ_MEAN_CSV = PROJECT_DIR / "pvz_selected_mean_k20.csv"
PVZ_EFF_CSV = PROJECT_DIR / "pvz_selected_effective_k20.csv"
PVZ_KEEP_CSV = PROJECT_DIR / "pvz_selected_effective_keep_zelenograd_k20.csv"

POLY_GPKG = PROJECT_DIR / "district_index_v2.gpkg"
POLY_LAYER = "districts_index_v2"

GRAPHML = Path(r"C:\Users\sgs-w\Downloads\moscow_walk.graphml")

OUT_CSV = PROJECT_DIR / "compare_k20_four_by_district.csv"

OUT_PNG_MEAN_MIN = PROJECT_DIR / "map_delta_mean_time_min_mean_vs_base.png"
OUT_PNG_MEAN_EFF = PROJECT_DIR / "map_delta_mean_time_effective_vs_base.png"
OUT_PNG_MEAN_KEEP = PROJECT_DIR / "map_delta_mean_time_effective_keep_vs_base.png"

OUT_PNG_SHARE_MIN = PROJECT_DIR / "map_delta_share10_min_mean_vs_base.png"
OUT_PNG_SHARE_EFF = PROJECT_DIR / "map_delta_share10_effective_vs_base.png"
OUT_PNG_SHARE_KEEP = PROJECT_DIR / "map_delta_share10_effective_keep_vs_base.png"

OUT_PNG_POINTS = PROJECT_DIR / "map_points_k20_four.png"

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
                try:
                    data["x"] = float(data["x"])
                except Exception:
                    pass
            if "y" in data:
                try:
                    data["y"] = float(data["y"])
                except Exception:
                    pass

        for _, _, _, data in _iter_edges(G):
            if "length" in data:
                try:
                    data["length"] = float(data["length"])
                except Exception:
                    pass
            if "walk_time_s" in data:
                try:
                    data["walk_time_s"] = float(data["walk_time_s"])
                except Exception:
                    pass
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
                try:
                    data["walk_time_s"] = float(data["walk_time_s"])
                except Exception:
                    pass
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
    m = np.isfinite(t) & np.isfinite(w) & (weights > 0)
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
        raise RuntimeError(f"{csv_path} должен содержать lat/lon")
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["lon"], df["lat"]), crs=WGS84)


def times_to_nearest(Gu, demand_nodes, pvz_nodes):
    dist = nx.multi_source_dijkstra_path_length(
        Gu, sources=pvz_nodes, weight="walk_time_s", cutoff=MAX_TIME_S
    )
    t_sec = np.array([float(dist.get(int(n), MAX_TIME_S)) for n in demand_nodes], dtype=float)
    t_sec = np.minimum(t_sec, float(MAX_TIME_S))
    return t_sec / 60.0


def save_delta_map(gmap, column, title, out_png):
    plt.figure(figsize=(10, 10))
    ax = plt.gca()
    gmap.plot(column=column, ax=ax, legend=True, missing_kwds={"color": "#cccccc"})
    ax.set_title(title)
    ax.set_axis_off()
    plt.tight_layout()
    plt.savefig(out_png, dpi=220)
    plt.close()


def main():
    demand = gpd.read_file(DEMAND_GPKG, layer=DEMAND_LAYER)
    if demand.crs is None:
        demand = demand.set_crs(METRIC_CRS, allow_override=True)
    if "district_name" not in demand.columns or "demand_w" not in demand.columns:
        raise RuntimeError("В demand_points должны быть district_name и demand_w.")
    demand_wgs = demand.to_crs(WGS84)

    G = load_graphml_robust(GRAPHML)
    G = ensure_walk_time(G)
    Gu = to_undirected_compat(G)

    demand_nodes = nearest_nodes_compat(Gu, X=demand_wgs.geometry.x.values, Y=demand_wgs.geometry.y.values)
    demand_nodes = np.array([int(x) for x in demand_nodes], dtype=np.int64)

    pvz_base = load_points(PVZ_BASE_CSV, K, ranked=True)
    pvz_mean = load_points(PVZ_MEAN_CSV, K, ranked=True)
    pvz_eff = load_points(PVZ_EFF_CSV, K, ranked=True)
    pvz_keep = load_points(PVZ_KEEP_CSV, K, ranked=True)

    pvz_base_nodes = list(set(int(x) for x in nearest_nodes_compat(Gu, X=pvz_base.geometry.x.values, Y=pvz_base.geometry.y.values)))
    pvz_mean_nodes = list(set(int(x) for x in nearest_nodes_compat(Gu, X=pvz_mean.geometry.x.values, Y=pvz_mean.geometry.y.values)))
    pvz_eff_nodes = list(set(int(x) for x in nearest_nodes_compat(Gu, X=pvz_eff.geometry.x.values, Y=pvz_eff.geometry.y.values)))
    pvz_keep_nodes = list(set(int(x) for x in nearest_nodes_compat(Gu, X=pvz_keep.geometry.x.values, Y=pvz_keep.geometry.y.values)))

    t_base = times_to_nearest(Gu, demand_nodes, pvz_base_nodes)
    t_mean = times_to_nearest(Gu, demand_nodes, pvz_mean_nodes)
    t_eff = times_to_nearest(Gu, demand_nodes, pvz_eff_nodes)
    t_keep = times_to_nearest(Gu, demand_nodes, pvz_keep_nodes)

    df = pd.DataFrame({
        "district_name": demand["district_name"].astype(str).values,
        "demand_w": demand["demand_w"].astype(float).values,
        "t_base": t_base,
        "t_mean": t_mean,
        "t_eff": t_eff,
        "t_keep": t_keep,
    })

    rows = []
    for name, g in df.groupby("district_name", sort=False):
        w = g["demand_w"].values

        mb = metrics(g["t_base"].values, w)
        mm = metrics(g["t_mean"].values, w)
        me = metrics(g["t_eff"].values, w)
        mk = metrics(g["t_keep"].values, w)

        if mb is None or mm is None or me is None or mk is None:
            continue

        row = {"district_name": name}

        for k, v in mb.items():
            row[f"{k}_base"] = v
        for k, v in mm.items():
            row[f"{k}_mean"] = v
        for k, v in me.items():
            row[f"{k}_eff"] = v
        for k, v in mk.items():
            row[f"{k}_keep"] = v

        row["delta_mean_minus_base"] = row["mean_time_min_mean"] - row["mean_time_min_base"]
        row["delta_eff_minus_base"] = row["mean_time_min_eff"] - row["mean_time_min_base"]
        row["delta_keep_minus_base"] = row["mean_time_min_keep"] - row["mean_time_min_base"]

        row["delta_share10_mean_minus_base"] = row["share_10min_mean"] - row["share_10min_base"]
        row["delta_share10_eff_minus_base"] = row["share_10min_eff"] - row["share_10min_base"]
        row["delta_share10_keep_minus_base"] = row["share_10min_keep"] - row["share_10min_base"]

        rows.append(row)

    out = pd.DataFrame(rows)
    out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    polys = gpd.read_file(POLY_GPKG, layer=POLY_LAYER)
    if polys.crs is None:
        polys = polys.set_crs(METRIC_CRS, allow_override=True)
    polys = polys.to_crs(WGS84)
    if "district_name" not in polys.columns:
        raise RuntimeError("В полигонах нет district_name.")

    gmap = polys.merge(out, on="district_name", how="left")

    save_delta_map(
        gmap,
        "delta_mean_minus_base",
        "Δ среднего времени (мин): (минимизация среднего) − (baseline охват 10 мин)",
        OUT_PNG_MEAN_MIN,
    )
    save_delta_map(
        gmap,
        "delta_eff_minus_base",
        "Δ среднего времени (мин): (эффективный спрос) − (baseline охват 10 мин)",
        OUT_PNG_MEAN_EFF,
    )
    save_delta_map(
        gmap,
        "delta_keep_minus_base",
        "Δ среднего времени (мин): (effective keep Zelenograd) − (baseline охват 10 мин)",
        OUT_PNG_MEAN_KEEP,
    )

    save_delta_map(
        gmap,
        "delta_share10_mean_minus_base",
        "Δ доли спроса ≤10 мин: (минимизация среднего) − (baseline охват 10 мин)",
        OUT_PNG_SHARE_MIN,
    )
    save_delta_map(
        gmap,
        "delta_share10_eff_minus_base",
        "Δ доли спроса ≤10 мин: (эффективный спрос) − (baseline охват 10 мин)",
        OUT_PNG_SHARE_EFF,
    )
    save_delta_map(
        gmap,
        "delta_share10_keep_minus_base",
        "Δ доли спроса ≤10 мин: (effective keep Zelenograd) − (baseline охват 10 мин)",
        OUT_PNG_SHARE_KEEP,
    )

    plt.figure(figsize=(10, 10))
    ax = plt.gca()
    polys.plot(ax=ax, color="#f0f0f0", edgecolor="#999999", linewidth=0.3)

    pvz_base.plot(ax=ax, color="red", markersize=28, marker="o", label="baseline (охват 10 мин)")
    pvz_mean.plot(ax=ax, color="blue", markersize=28, marker="^", label="минимизация среднего")
    pvz_eff.plot(ax=ax, color="green", markersize=28, marker="s", label="эффективный спрос")
    pvz_keep.plot(ax=ax, color="black", markersize=28, marker="x", label="effective keep Zelenograd")

    ax.set_title("Четыре сети K=20")
    ax.set_axis_off()
    ax.legend(loc="lower left", frameon=True)
    plt.tight_layout()
    plt.savefig(OUT_PNG_POINTS, dpi=220)
    plt.close()

    print("ГОТОВО")
    print("CSV :", OUT_CSV)
    print("PNG :", OUT_PNG_MEAN_MIN)
    print("PNG :", OUT_PNG_MEAN_EFF)
    print("PNG :", OUT_PNG_MEAN_KEEP)
    print("PNG :", OUT_PNG_SHARE_MIN)
    print("PNG :", OUT_PNG_SHARE_EFF)
    print("PNG :", OUT_PNG_SHARE_KEEP)
    print("PNG :", OUT_PNG_POINTS)


if __name__ == "__main__":
    main()