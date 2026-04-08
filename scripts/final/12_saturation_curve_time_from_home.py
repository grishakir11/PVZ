# 12_saturation_curve_time_from_home.py
# Кривые насыщения по "удобству жителям":
# K -> mean/p50/p90 времени пешком от demand точек до ближайшего ПВЗ (взвешенно по demand_w).
#
# Использует только "от дома" (demand points) и выбранные ПВЗ. Без метро.
#
# Вход:
#   - pvz_project/demand_points.gpkg (layer: demand_points)  (demand_w)
#   - pvz_project/pvz_selected_kmax.csv  (sel_rank, lat, lon)  (из 11_saturation_curve_share10.py)
#   - moscow_walk.graphml
#
# Выход:
#   - pvz_project/saturation_curve_time_from_home.csv
#   - pvz_project/saturation_curve_time_from_home.png

from pathlib import Path
from time import perf_counter
import math

import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
import osmnx as ox
import matplotlib.pyplot as plt


# ====== SETTINGS ======
PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

DEMAND_GPKG = PROJECT_DIR / "demand_points.gpkg"
DEMAND_LAYER = "demand_points"

PVZ_RANKED_CSV = PROJECT_DIR / "pvz_selected_kmax.csv"

GRAPHML = Path(r"C:\Users\sgs-w\Downloads\moscow_walk.graphml")

OUT_CSV = PROJECT_DIR / "saturation_curve_time_from_home.csv"
OUT_PNG = PROJECT_DIR / "saturation_curve_time_from_home.png"

WGS84 = "EPSG:4326"
METRIC_CRS = "EPSG:32637"

# какие K смотреть
K_LIST = [5, 10, 20, 30, 40, 60]

# чтобы не ловить бесконечности и не бегать по всему графу каждый раз:
# считаем расстояния до ПВЗ с отсечкой. Всё что дальше — считаем как ">= MAX_TIME_S".
MAX_TIME_S = 5400  # 90 минут

# если в графе нет walk_time_s
WALK_SPEED_MPS = 1.3
# ======================


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


def main():
    t0 = perf_counter()

    print("[1/6] Load demand points ...")
    demand = gpd.read_file(DEMAND_GPKG, layer=DEMAND_LAYER)
    if demand.crs is None:
        demand = demand.set_crs(METRIC_CRS, allow_override=True)
    if "demand_w" not in demand.columns:
        raise RuntimeError("В demand_points нет demand_w.")
    demand_wgs = demand.to_crs(WGS84)

    total_demand = float(demand["demand_w"].sum())
    print(f"  demand_points={len(demand):,} total_demand_w={total_demand:,.0f}")

    print("[2/6] Load ranked PVZ list ...")
    pvz = pd.read_csv(PVZ_RANKED_CSV, encoding="utf-8-sig")
    need = {"sel_rank", "lat", "lon"}
    if not need.issubset(pvz.columns):
        raise RuntimeError(f"pvz_selected_kmax.csv должен иметь {need}.")
    pvz = pvz.sort_values("sel_rank").reset_index(drop=True)
    kmax = int(pvz["sel_rank"].max())
    if max(K_LIST) > kmax:
        raise RuntimeError(f"K_LIST содержит K>{kmax}. Пересчитай pvz_selected_kmax.csv с большим Kmax.")
    print(f"  pvz_ranked_count={len(pvz)} (kmax={kmax})")

    print("[3/6] Load graph ...")
    G = load_graphml_robust(GRAPHML)
    G = ensure_walk_time(G)
    Gu = to_undirected_compat(G)
    print(f"  G nodes={len(Gu.nodes):,} edges={len(Gu.edges):,}")

    print("[4/6] Snap demand to nodes once ...")
    demand_nodes = nearest_nodes_compat(Gu, X=demand_wgs.geometry.x.values, Y=demand_wgs.geometry.y.values)
    demand_nodes = np.array([int(x) for x in demand_nodes], dtype=np.int64)

    # агрегируем спрос по node
    node_weight = {}
    for n, w in zip(demand_nodes, demand["demand_w"].astype(float).values):
        if not math.isfinite(w) or w <= 0:
            continue
        node_weight[int(n)] = node_weight.get(int(n), 0.0) + float(w)

    demand_node_list = np.array(list(node_weight.keys()), dtype=np.int64)
    demand_w_list = np.array([node_weight[int(n)] for n in demand_node_list], dtype=float)

    print(f"  demand_nodes_unique={len(demand_node_list):,}")

    print("[5/6] Incremental add PVZ + update best times ...")
    best_time = {int(n): float("inf") for n in demand_node_list.tolist()}

    records = []
    pvz_nodes_seen = set()
    K_set = set(K_LIST)

    for i in range(max(K_LIST)):
        row = pvz.iloc[i]
        pvz_pt = gpd.GeoSeries(
            gpd.points_from_xy([row["lon"]], [row["lat"]], crs=WGS84)
        )
        src = int(nearest_nodes_compat(Gu, X=[pvz_pt.geometry.x.values[0]], Y=[pvz_pt.geometry.y.values[0]])[0])

        # пропускаем дубликаты по node
        if src in pvz_nodes_seen:
            continue
        pvz_nodes_seen.add(src)

        dist = nx.single_source_dijkstra_path_length(
            Gu,
            source=src,
            cutoff=MAX_TIME_S,
            weight="walk_time_s",
        )

        # обновляем best_time только для demand nodes
        for n in dist.keys():
            if n in best_time:
                d = float(dist[n])
                if d < best_time[n]:
                    best_time[n] = d

        k_now = len(pvz_nodes_seen)
        if k_now in K_set:
            t_sec = np.array([min(best_time[int(n)], MAX_TIME_S) for n in demand_node_list], dtype=float)
            t_min = t_sec / 60.0

            mean_min = float(np.sum(t_min * demand_w_list) / np.sum(demand_w_list))
            p50 = weighted_quantile(t_min, demand_w_list, 0.50)
            p90 = weighted_quantile(t_min, demand_w_list, 0.90)

            capped_share = float(np.sum(demand_w_list[t_sec >= MAX_TIME_S]) / np.sum(demand_w_list))

            records.append({
                "K": k_now,
                "mean_time_min": mean_min,
                "p50_time_min": p50,
                "p90_time_min": p90,
                "capped_share_ge_90min": capped_share,
                "max_time_cap_min": MAX_TIME_S / 60.0,
            })

            print(f"  K={k_now:>3d}: mean={mean_min:.1f}m p50={p50:.1f}m p90={p90:.1f}m capped={capped_share:.3f}")

    df = pd.DataFrame(records).sort_values("K")
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    print("[6/6] Plot ...")
    if len(df) > 0:
        plt.figure()
        plt.plot(df["K"].values, df["mean_time_min"].values, marker="o", label="mean time (min)")
        plt.plot(df["K"].values, df["p50_time_min"].values, marker="o", label="p50 time (min)")
        plt.plot(df["K"].values, df["p90_time_min"].values, marker="o", label="p90 time (min)")
        plt.xlabel("Number of PVZ (K)")
        plt.ylabel("Walking time from home to nearest PVZ (min)")
        plt.title("Saturation curve: K -> time to nearest PVZ (from home)")
        plt.grid(True)
        plt.legend()
        plt.tight_layout()
        plt.savefig(OUT_PNG, dpi=160)

    t1 = perf_counter()
    print("DONE")
    print("CSV:", OUT_CSV)
    print("PNG:", OUT_PNG)
    print(f"TOTAL dt={t1 - t0:.1f}s)")


if __name__ == "__main__":
    main()
