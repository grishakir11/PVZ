# 20_select_effective_k20_keep_zelenograd.py
# K=20: максимизация "эффективного спроса" D = sum w_i * f(t_i),
# но с фиксированием базовых точек в Зеленограде (чтобы не получить -1 по доле <=10 мин там).
#
# Вход:
#   pvz_project/demand_points.gpkg (layer: demand_points)   (demand_w)
#   pvz_project/candidate_points.gpkg (layer: candidate_points) (желательно local_demand_w)
#   pvz_project/pvz_selected_kmax.csv (baseline, берём первые 20 и фиксируем зел-дистрикты)
#   pvz_project/pvz_selected_mean_k20.csv (для сравнения)
#   pvz_project/pvz_selected_effective_k20.csv (для сравнения)
#   moscow_walk.graphml
#
# Выход:
#   pvz_project/pvz_selected_effective_keep_zelenograd_k20.csv
#   pvz_project/compare_k20_four_objectives.csv

from pathlib import Path
import math
import heapq
from time import perf_counter

import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
import osmnx as ox

PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

DEMAND_GPKG = PROJECT_DIR / "demand_points.gpkg"
DEMAND_LAYER = "demand_points"

CAND_GPKG = PROJECT_DIR / "candidate_points.gpkg"
CAND_LAYER = "candidate_points"

PVZ_RANKED_CSV = PROJECT_DIR / "pvz_selected_kmax.csv"              # baseline (первые 20)
PVZ_MEAN_CSV   = PROJECT_DIR / "pvz_selected_mean_k20.csv"          # min mean
PVZ_EFF_CSV    = PROJECT_DIR / "pvz_selected_effective_k20.csv"     # unconstrained effective

GRAPHML = Path(r"C:\Users\sgs-w\Downloads\moscow_walk.graphml")

OUT_PVZ = PROJECT_DIR / "pvz_selected_effective_keep_zelenograd_k20.csv"
OUT_CMP = PROJECT_DIR / "compare_k20_four_objectives.csv"

WGS84 = "EPSG:4326"
METRIC_CRS = "EPSG:32637"

K = 20
MAX_TIME_S = 10800          # 180 минут
MAX_CANDIDATES_USED = 900   # кандидаты
DEMAND_WEIGHT_CUM_FRAC = 0.95
WALK_SPEED_MPS = 1.3

# Районы Зеленограда (по твоим таблицам)
ZEL_DISTRICTS = {"Матушкино", "Савёлки", "Силино", "Старое Крюково", "Крюково"}


def f_time_minutes(t_min: np.ndarray) -> np.ndarray:
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


def metrics_from_times(times_sec, weights):
    t = np.minimum(np.asarray(times_sec, dtype=float), float(MAX_TIME_S))
    w = np.asarray(weights, dtype=float)
    wsum = float(w.sum())
    tmin = t / 60.0

    mean = float((tmin * w).sum() / wsum)
    p50 = weighted_quantile(tmin, w, 0.50)
    p90 = weighted_quantile(tmin, w, 0.90)
    share10 = float(w[t <= 600].sum() / wsum)

    D = float(np.sum(w * f_time_minutes(tmin)))
    return {
        "share_10min": share10,
        "mean_time_min": mean,
        "p50_time_min": p50,
        "p90_time_min": p90,
        "D_effective": D,
        "D_effective_share": D / wsum if wsum > 0 else np.nan,
        "cap_min": MAX_TIME_S / 60.0,
    }


def times_for_pvz_nodes(Gu, demand_nodes, pvz_nodes):
    dist = nx.multi_source_dijkstra_path_length(Gu, sources=pvz_nodes, weight="walk_time_s", cutoff=MAX_TIME_S)
    return np.array([float(dist.get(int(n), MAX_TIME_S)) for n in demand_nodes], dtype=float)


def load_points_csv(csv_path: Path, k: int, ranked=True) -> gpd.GeoDataFrame:
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    if ranked and "sel_rank" in df.columns:
        df = df.sort_values("sel_rank")
    df = df.head(k).copy()
    if not {"lat", "lon"}.issubset(df.columns):
        raise RuntimeError(f"{csv_path} должен содержать lat/lon")
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["lon"], df["lat"]), crs=WGS84)


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

    cand_use = cand.copy()
    if "local_demand_w" in cand_use.columns:
        cand_use = cand_use.sort_values("local_demand_w", ascending=False)
    if len(cand_use) > MAX_CANDIDATES_USED:
        cand_use = cand_use.head(MAX_CANDIDATES_USED).copy()
    print(f"  demand_points={len(demand):,}, candidates_used={len(cand_use):,}")

    print("[2/7] Load graph ...")
    G = load_graphml_robust(GRAPHML)
    G = ensure_walk_time(G)
    Gu = to_undirected_compat(G)
    print(f"  G nodes={len(Gu.nodes):,} edges={len(Gu.edges):,}")

    print("[3/7] Snap demand to nodes + aggregate weights (keep top weight mass) ...")
    demand_wgs = demand.to_crs(WGS84)
    dn = nearest_nodes_compat(Gu, X=demand_wgs.geometry.x.values, Y=demand_wgs.geometry.y.values)
    dn = np.array([int(x) for x in dn], dtype=np.int64)
    dw = demand["demand_w"].astype(float).values

    node_w = {}
    for n, w in zip(dn, dw):
        if not math.isfinite(w) or w <= 0:
            continue
        node_w[int(n)] = node_w.get(int(n), 0.0) + float(w)

    items = sorted(node_w.items(), key=lambda kv: kv[1], reverse=True)
    total_w = float(sum(w for _, w in items))

    keep = []
    cum = 0.0
    for n, w in items:
        keep.append((n, w))
        cum += w
        if cum / total_w >= DEMAND_WEIGHT_CUM_FRAC:
            break

    demand_nodes = np.array([n for n, _ in keep], dtype=np.int64)
    demand_wts = np.array([w for _, w in keep], dtype=float)
    print(f"  demand_nodes_unique_kept={len(demand_nodes):,} kept_weight_share={demand_wts.sum()/total_w:.3f}")

    node_index = {int(n): i for i, n in enumerate(demand_nodes.tolist())}

    print("[4/7] Fixed PVZ from baseline in Zelenograd ...")
    base20 = pd.read_csv(PVZ_RANKED_CSV, encoding="utf-8-sig").sort_values("sel_rank").head(K).copy()
    if "district_name" not in base20.columns:
        raise RuntimeError("В pvz_selected_kmax.csv нет district_name, фиксация Зеленограда невозможна.")
    fixed = base20[base20["district_name"].astype(str).isin(ZEL_DISTRICTS)].copy()
    fixed_gdf = gpd.GeoDataFrame(fixed, geometry=gpd.points_from_xy(fixed["lon"], fixed["lat"]), crs=WGS84)

    fixed_nodes = nearest_nodes_compat(Gu, X=fixed_gdf.geometry.x.values, Y=fixed_gdf.geometry.y.values)
    fixed_nodes = list(set(int(x) for x in fixed_nodes))
    fixed_cnt = len(fixed_nodes)
    if fixed_cnt == 0:
        raise RuntimeError("Не нашёл ни одной baseline-точки в Зеленограде. Проверь district_name.")
    if fixed_cnt >= K:
        raise RuntimeError("Слишком много фиксированных точек, K не хватает.")

    print(f"  fixed_nodes={fixed_cnt} (Zelenograd), remaining_to_pick={K - fixed_cnt}")

    # текущее лучшее время/предпочтение от фиксированных узлов
    dist_fixed = nx.multi_source_dijkstra_path_length(Gu, sources=fixed_nodes, weight="walk_time_s", cutoff=MAX_TIME_S)
    best_time = np.array([float(dist_fixed.get(int(n), MAX_TIME_S)) for n in demand_nodes], dtype=float)
    best_time = np.minimum(best_time, float(MAX_TIME_S))
    best_pref = f_time_minutes(best_time / 60.0)

    print("[5/7] Snap candidates to nodes + deduplicate ...")
    cand_wgs = cand_use.to_crs(WGS84)
    cn = nearest_nodes_compat(Gu, X=cand_wgs.geometry.x.values, Y=cand_wgs.geometry.y.values)
    cn = np.array([int(x) for x in cn], dtype=np.int64)

    # дедуп по узлу
    seen = set()
    keep_idx = []
    for i, n in enumerate(cn.tolist()):
        if n in seen:
            continue
        seen.add(n)
        keep_idx.append(i)
    cand_use = cand_use.iloc[keep_idx].copy()
    cn = cn[keep_idx]

    # выкинуть кандидатов, которые совпадают с уже фиксированными узлами
    mask = np.array([n not in set(fixed_nodes) for n in cn.tolist()], dtype=bool)
    cand_use = cand_use.loc[mask].copy()
    cn = cn[mask]
    print(f"  candidates_unique_nodes_after_filter={len(cand_use):,}")

    print("[6/7] Precompute candidate->pairs and lazy greedy (maximize effective demand) ...")
    cand_pairs = []
    init_gain = np.zeros(len(cn), dtype=float)

    for j, src in enumerate(cn.tolist()):
        dist = nx.single_source_dijkstra_path_length(Gu, source=int(src), cutoff=MAX_TIME_S, weight="walk_time_s")
        pairs = []
        g = 0.0
        for node, d in dist.items():
            idx = node_index.get(int(node), None)
            if idx is None:
                continue
            dd = float(d)
            pairs.append((idx, dd))
            # прирост предпочтения относительно текущего best_pref
            if dd < best_time[idx]:
                new_pref = float(f_time_minutes(np.array([dd / 60.0]))[0])
                g += demand_wts[idx] * (new_pref - best_pref[idx])
        cand_pairs.append(pairs)
        init_gain[j] = g
        if (j + 1) % 100 == 0:
            print(f"  precomputed {j+1}/{len(cn)}")

    selected = []
    selected_set = set()
    heap = []
    for j in range(len(cn)):
        heapq.heappush(heap, (-float(init_gain[j]), j))

    def gain_now(j: int) -> float:
        g = 0.0
        for idx, d in cand_pairs[j]:
            cur = best_time[idx]
            if d < cur:
                new_pref = float(f_time_minutes(np.array([d / 60.0]))[0])
                g += demand_wts[idx] * (new_pref - best_pref[idx])
        return g

    need_pick = K - fixed_cnt
    while len(selected) < need_pick and heap:
        neg_g, j = heapq.heappop(heap)
        if j in selected_set:
            continue

        gcur = gain_now(j)
        if gcur < (-neg_g) * 0.98:
            heapq.heappush(heap, (-float(gcur), j))
            continue

        selected.append(j)
        selected_set.add(j)

        for idx, d in cand_pairs[j]:
            if d < best_time[idx]:
                best_time[idx] = d
                best_pref[idx] = float(f_time_minutes(np.array([d / 60.0]))[0])

        print(f"  pick {len(selected)}/{need_pick}: gain={gcur:,.0f}")

    # собрать итоговые точки: fixed + selected
    fixed_out = fixed_gdf.copy()
    fixed_out["source"] = "fixed_zelenograd"
    fixed_out = fixed_out[["lon", "lat", "district_name", "source"]].copy()

    sel_gdf = cand_use.iloc[selected].copy().to_crs(WGS84)
    sel_out = pd.DataFrame({
        "lon": sel_gdf.geometry.x.astype(float).values,
        "lat": sel_gdf.geometry.y.astype(float).values,
        "district_name": sel_gdf.get("district_name", "").astype(str).values,
        "source": ["chosen_effective"] * len(sel_gdf),
    })

    out_df = pd.concat([fixed_out, sel_out], ignore_index=True)
    out_df["sel_rank"] = np.arange(1, len(out_df) + 1)
    out_df = out_df[["sel_rank", "lat", "lon", "district_name", "source"]]
    out_df.to_csv(OUT_PVZ, index=False, encoding="utf-8-sig")

    print("[7/7] Compare 4 objectives on same demand subset ...")
    # baseline 20
    pvz_base = load_points_csv(PVZ_RANKED_CSV, K, ranked=True)
    base_nodes = list(set(int(x) for x in nearest_nodes_compat(Gu, X=pvz_base.geometry.x.values, Y=pvz_base.geometry.y.values)))
    t_base = times_for_pvz_nodes(Gu, demand_nodes, base_nodes)

    # min mean
    pvz_mean = load_points_csv(PVZ_MEAN_CSV, K, ranked=True)
    mean_nodes = list(set(int(x) for x in nearest_nodes_compat(Gu, X=pvz_mean.geometry.x.values, Y=pvz_mean.geometry.y.values)))
    t_mean = times_for_pvz_nodes(Gu, demand_nodes, mean_nodes)

    # unconstrained effective
    pvz_eff = load_points_csv(PVZ_EFF_CSV, K, ranked=True)
    eff_nodes = list(set(int(x) for x in nearest_nodes_compat(Gu, X=pvz_eff.geometry.x.values, Y=pvz_eff.geometry.y.values)))
    t_eff = times_for_pvz_nodes(Gu, demand_nodes, eff_nodes)

    # constrained effective (this)
    pvz_keep = load_points_csv(OUT_PVZ, K, ranked=True)
    keep_nodes = list(set(int(x) for x in nearest_nodes_compat(Gu, X=pvz_keep.geometry.x.values, Y=pvz_keep.geometry.y.values)))
    t_keep = times_for_pvz_nodes(Gu, demand_nodes, keep_nodes)

    cmp = pd.DataFrame([
        {"method": "baseline_coverage10", **metrics_from_times(t_base, demand_wts)},
        {"method": "min_mean_time", **metrics_from_times(t_mean, demand_wts)},
        {"method": "max_effective_demand", **metrics_from_times(t_eff, demand_wts)},
        {"method": "effective_keep_zelenograd", **metrics_from_times(t_keep, demand_wts)},
    ])
    cmp.to_csv(OUT_CMP, index=False, encoding="utf-8-sig")

    t1 = perf_counter()
    print("DONE")
    print("PVZ CSV:", OUT_PVZ)
    print("COMPARE CSV:", OUT_CMP)
    print(f"TOTAL dt={t1 - t0:.1f}s)")


if __name__ == "__main__":
    main()