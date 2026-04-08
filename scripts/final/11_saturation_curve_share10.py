# 11_saturation_curve_share10.py
# Кривая насыщения: K -> share_10min (доля спроса, у которого ближайший ПВЗ <=10 минут пешком).
# Выбираем ПВЗ greedily по Max Coverage (покрытие спроса <=10 мин) и снимаем метрики для разных K.
#
# Вход:
#   - pvz_project/demand_points.gpkg (layer: demand_points)  (demand_w)
#   - pvz_project/candidate_points.gpkg (layer: candidate_points) (желательно local_demand_w)
#   - moscow_walk.graphml
#
# Выход:
#   - pvz_project/saturation_curve_share10.csv
#   - pvz_project/saturation_curve_share10.png
#   - pvz_project/pvz_selected_kmax.csv  (точки для максимального K)

from pathlib import Path
from time import perf_counter
import math
import heapq

import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
import osmnx as ox
import matplotlib.pyplot as plt


# ====== НАСТРОЙКИ ======
PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

DEMAND_GPKG = PROJECT_DIR / "demand_points.gpkg"
DEMAND_LAYER = "demand_points"

CAND_GPKG = PROJECT_DIR / "candidate_points.gpkg"
CAND_LAYER = "candidate_points"

GRAPHML = Path(r"C:\Users\sgs-w\Downloads\moscow_walk.graphml")

OUT_CSV = PROJECT_DIR / "saturation_curve_share10.csv"
OUT_PNG = PROJECT_DIR / "saturation_curve_share10.png"
OUT_PVZ_CSV = PROJECT_DIR / "pvz_selected_kmax.csv"

WGS84 = "EPSG:4326"
METRIC_CRS = "EPSG:32637"

# Порог "10 минут" для покрытия
WALK_TIME_CUTOFF_S = 600

# Список K, по которым хотим точки на кривой
K_LIST = [5, 10, 20, 30, 40, 60]

# Чтобы не убить время/память: ограничим число кандидатов
MAX_CANDIDATES_USED = 3500

# Если в графе нет walk_time_s
WALK_SPEED_MPS = 1.3

# =======================


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
    except Exception as e:
        print(f"  ox.load_graphml failed: {e}")
        print("  fallback: networkx.read_graphml ...")

    G = nx.read_graphml(path)

    # узлы могут быть строками -> int где возможно
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

    # x/y -> float
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

    # edge attrs -> float
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


def main():
    t0 = perf_counter()

    print("[1/7] Load demand + candidates ...")
    demand = gpd.read_file(DEMAND_GPKG, layer=DEMAND_LAYER)
    cand = gpd.read_file(CAND_GPKG, layer=CAND_LAYER)

    if demand.crs is None:
        demand = demand.set_crs(METRIC_CRS, allow_override=True)
    if cand.crs is None:
        cand = cand.set_crs(METRIC_CRS, allow_override=True)

    if "demand_w" not in demand.columns:
        raise RuntimeError("В demand_points нет demand_w.")

    total_demand = float(demand["demand_w"].sum())
    print(f"  demand_points={len(demand):,} total_demand_w={total_demand:,.0f}")
    print(f"  candidates_raw={len(cand):,}")

    # ограничим кандидатов
    cand_use = cand.copy()
    if "local_demand_w" in cand_use.columns:
        cand_use = cand_use.sort_values("local_demand_w", ascending=False)
    if len(cand_use) > MAX_CANDIDATES_USED:
        cand_use = cand_use.head(MAX_CANDIDATES_USED).copy()
    print(f"  candidates_used={len(cand_use):,}")

    print("[2/7] Load graph ...")
    G = load_graphml_robust(GRAPHML)
    G = ensure_walk_time(G)
    Gu = to_undirected_compat(G)
    print(f"  G nodes={len(Gu.nodes):,} edges={len(Gu.edges):,}")

    print("[3/7] Snap demand/candidates to graph nodes ...")
    demand_wgs = demand.to_crs(WGS84)
    cand_wgs = cand_use.to_crs(WGS84)

    demand_nodes = nearest_nodes_compat(Gu, X=demand_wgs.geometry.x.values, Y=demand_wgs.geometry.y.values)
    cand_nodes = nearest_nodes_compat(Gu, X=cand_wgs.geometry.x.values, Y=cand_wgs.geometry.y.values)

    demand_nodes = np.array([int(x) for x in demand_nodes], dtype=np.int64)
    cand_nodes = np.array([int(x) for x in cand_nodes], dtype=np.int64)

    # агрегируем спрос по node
    node_weight = {}
    for n, w in zip(demand_nodes, demand["demand_w"].astype(float).values):
        if not math.isfinite(w) or w <= 0:
            continue
        node_weight[int(n)] = node_weight.get(int(n), 0.0) + float(w)
    demand_nodes_set = set(node_weight.keys())
    print(f"  demand_nodes_unique={len(demand_nodes_set):,}")

    # дедуп кандидатов по node (оставим один на node)
    # если есть local_demand_w, он уже отсортирован, значит сохраняем лучший
    seen = set()
    keep_idx = []
    for i, n in enumerate(cand_nodes.tolist()):
        if n in seen:
            continue
        seen.add(n)
        keep_idx.append(i)

    cand_use = cand_use.iloc[keep_idx].copy()
    cand_nodes = cand_nodes[keep_idx]
    print(f"  candidates_unique_nodes={len(cand_use):,}")

    t1 = perf_counter()
    print(f"  ok (dt={t1 - t0:.1f}s)")

    print("[4/7] Precompute coverage sets for each candidate (<=10 min) ...")
    coverage = []
    coverage_gain0 = []

    for i, src in enumerate(cand_nodes.tolist()):
        dist = nx.single_source_dijkstra_path_length(
            Gu, source=int(src), cutoff=WALK_TIME_CUTOFF_S, weight="walk_time_s"
        )
        cov_nodes = [n for n in dist.keys() if n in demand_nodes_set]

        g = 0.0
        for n in cov_nodes:
            g += node_weight[n]

        coverage.append(cov_nodes)
        coverage_gain0.append(g)

        if (i + 1) % 200 == 0:
            print(f"  processed {i+1}/{len(cand_nodes)} candidates")

    t2 = perf_counter()
    print(f"  ok (dt={t2 - t1:.1f}s)")

    print("[5/7] Greedy selection up to Kmax ...")
    Kmax = max(K_LIST)
    selected = []
    covered_total = 0.0
    uncovered = dict(node_weight)

    records = []

    for step in range(Kmax):
        best_i = None
        best_gain = 0.0

        for i, cov in enumerate(coverage):
            if i in selected:
                continue
            gain = 0.0
            for n in cov:
                gain += uncovered.get(n, 0.0)
            if gain > best_gain:
                best_gain = gain
                best_i = i

        if best_i is None or best_gain <= 0:
            print(f"  stop at step={step+1}: no positive gain")
            break

        selected.append(best_i)

        # обновить covered_total / uncovered
        for n in coverage[best_i]:
            w = uncovered.pop(n, 0.0)
            covered_total += w

        k_now = step + 1
        if k_now in K_LIST:
            share10 = covered_total / total_demand if total_demand > 0 else float("nan")
            records.append({
                "K": k_now,
                "covered_demand_w_10min": covered_total,
                "total_demand_w": total_demand,
                "share_10min": share10,
                "gain_last": best_gain,
            })
            print(f"  K={k_now:>3d}: share_10min={share10:.4f} covered={covered_total:,.0f} gain_last={best_gain:,.0f}")

    t3 = perf_counter()
    print(f"  ok (dt={t3 - t2:.1f}s)")

    print("[6/7] Save curve CSV + plot ...")
    df = pd.DataFrame(records).sort_values("K")
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    # plot
    if len(df) > 0:
        plt.figure()
        plt.plot(df["K"].values, df["share_10min"].values, marker="o")
        plt.xlabel("Number of PVZ (K)")
        plt.ylabel("Share of demand within 10 min")
        plt.title("Saturation curve: K -> share_10min")
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(OUT_PNG, dpi=160)

    print("  CSV:", OUT_CSV)
    print("  PNG:", OUT_PNG)

    print("[7/7] Save PVZ points for Kmax (for maps) ...")
    # координаты выбранных точек для максимального K, чтобы рисовать
    sel_idx = selected[:max(K_LIST)]
    pvz_sel = cand_use.iloc[sel_idx].copy().to_crs(WGS84)
    out_pvz = pd.DataFrame({
        "sel_rank": np.arange(1, len(pvz_sel) + 1),
        "lat": pvz_sel.geometry.y.astype(float).values,
        "lon": pvz_sel.geometry.x.astype(float).values,
        "district_name": pvz_sel.get("district_name", "").astype(str).values,
    })
    out_pvz.to_csv(OUT_PVZ_CSV, index=False, encoding="utf-8-sig")
    print("  PVZ CSV:", OUT_PVZ_CSV)

    t4 = perf_counter()
    print(f"DONE (total dt={t4 - t0:.1f}s)")


if __name__ == "__main__":
    main()
