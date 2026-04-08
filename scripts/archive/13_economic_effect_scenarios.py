# 13_economic_effect_scenarios.py
# Экономический эффект расширения сети ПВЗ на метриках "от дома" (пешком по графу).
#
# Идея:
# 1) Есть точки спроса с весом demand_w (прокси спроса жителей).
# 2) Есть набор ПВЗ (первые K точек из pvz_selected_kmax.csv).
# 3) Считаем время до ближайшего ПВЗ по пешеходному графу -> t_i(K).
# 4) Вводим функцию предпочтения f(t): чем дальше идти, тем меньше "конверсия".
# 5) Эффективный спрос: D(K) = sum_i demand_w_i * f(t_i(K)).
# 6) Для перехода K0 -> K1 считаем ΔD и переводим в деньги сценарно.
#
# Вход:
#   - pvz_project/demand_points.gpkg (layer: demand_points)  (demand_w)
#   - pvz_project/pvz_selected_kmax.csv  (sel_rank, lat, lon)  (из 11_saturation_curve_share10.py)
#   - moscow_walk.graphml
#
# Выход:
#   - pvz_project/econ_k_metrics.csv
#   - pvz_project/econ_transitions.csv
#   - pvz_project/econ_scenarios.csv

from pathlib import Path
from time import perf_counter
import math

import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
import osmnx as ox


# ====== ПУТИ ======
PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

DEMAND_GPKG = PROJECT_DIR / "demand_points.gpkg"
DEMAND_LAYER = "demand_points"

PVZ_RANKED_CSV = PROJECT_DIR / "pvz_selected_kmax.csv"

GRAPHML = Path(r"C:\Users\sgs-w\Downloads\moscow_walk.graphml")

OUT_K = PROJECT_DIR / "econ_k_metrics.csv"
OUT_TR = PROJECT_DIR / "econ_transitions.csv"
OUT_SC = PROJECT_DIR / "econ_scenarios.csv"

WGS84 = "EPSG:4326"
METRIC_CRS = "EPSG:32637"
# ====================


# ====== НАСТРОЙКИ РАСЧЁТА ======
# Какие K считаем (должны быть <= kmax в pvz_selected_kmax.csv)
K_LIST = [20, 30, 40, 60]

# Ограничение по времени для ускорения (всё что дальше считаем как MAX_TIME_S)
MAX_TIME_S = 10800  # 180 минут, чтобы p90 не залипал на 90

# Если в графе нет walk_time_s
WALK_SPEED_MPS = 1.3
# ===============================


# ====== f(t): "готовность пользоваться ПВЗ" от времени пешком (мин) ======
# Можно менять числа, это сценарная модель.
# Важно: функция убывающая.
# Здесь задана простая кусочная зависимость.
def f_time_minutes(t_min: np.ndarray) -> np.ndarray:
    t = np.asarray(t_min, dtype=float)
    out = np.zeros_like(t, dtype=float)

    # <=10 мин
    m = t <= 10
    out[m] = 1.00

    # (10,20]
    m = (t > 10) & (t <= 20)
    out[m] = 0.85

    # (20,30]
    m = (t > 20) & (t <= 30)
    out[m] = 0.70

    # (30,45]
    m = (t > 30) & (t <= 45)
    out[m] = 0.50

    # (45,60]
    m = (t > 45) & (t <= 60)
    out[m] = 0.35

    # >60 мин
    m = t > 60
    out[m] = 0.20

    return out
# ========================================================================


# ====== СЦЕНАРИИ ДЕНЕГ ======
# q = "сколько выдач в месяц на 1 единицу D"
# m = маржинальный доход на выдачу (руб)
# c_fix = фиксированные затраты на 1 новый ПВЗ в месяц (руб/мес)
# c_open = единовременные затраты на открытие 1 ПВЗ (руб)
SCENARIOS = [
    {"name": "Пессимистичный", "q": 0.8, "m": 35, "c_fix": 280_000, "c_open": 900_000},
    {"name": "Базовый",       "q": 1.0, "m": 50, "c_fix": 240_000, "c_open": 800_000},
    {"name": "Оптимистичный", "q": 1.2, "m": 70, "c_fix": 210_000, "c_open": 700_000},
]
# ===========================


# ====== ВСПОМОГАТЕЛЬНОЕ: граф и типы ======
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

        # node ids -> int where possible
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
# =========================================


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

    print("[1/6] Read demand points ...")
    demand = gpd.read_file(DEMAND_GPKG, layer=DEMAND_LAYER)
    if demand.crs is None:
        demand = demand.set_crs(METRIC_CRS, allow_override=True)
    if "demand_w" not in demand.columns:
        raise RuntimeError("В demand_points нет demand_w.")

    demand_wgs = demand.to_crs(WGS84)
    total_w = float(demand["demand_w"].astype(float).sum())
    print(f"  demand_points={len(demand):,} total_demand_w={total_w:,.0f}")

    print("[2/6] Read ranked PVZ list ...")
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

    print("[4/6] Snap demand nodes (one-time) ...")
    demand_nodes = nearest_nodes_compat(Gu, X=demand_wgs.geometry.x.values, Y=demand_wgs.geometry.y.values)
    demand_nodes = np.array([int(x) for x in demand_nodes], dtype=np.int64)
    w_arr_raw = demand["demand_w"].astype(float).values

    # агрегируем спрос по узлам графа (если несколько demand точек попали в один узел)
    node_to_w = {}
    for n, w in zip(demand_nodes, w_arr_raw):
        if not math.isfinite(w) or w <= 0:
            continue
        node_to_w[int(n)] = node_to_w.get(int(n), 0.0) + float(w)

    demand_node_list = np.array(list(node_to_w.keys()), dtype=np.int64)
    demand_w_list = np.array([node_to_w[int(n)] for n in demand_node_list], dtype=float)
    total_w = float(demand_w_list.sum())
    print(f"  demand_nodes_unique={len(demand_node_list):,} total_demand_w={total_w:,.0f}")

    # мапа node -> индекс массива
    node_index = {int(n): i for i, n in enumerate(demand_node_list.tolist())}

    print("[5/6] Incremental evaluate K (update best_time) ...")
    best_time = np.full(len(demand_node_list), np.inf, dtype=float)

    # добавляем ПВЗ по рангу и обновляем best_time
    pvz_nodes_seen = set()
    results_k = []

    K_set = set(K_LIST)
    K_target_max = max(K_LIST)

    for i in range(len(pvz)):
        if len(pvz_nodes_seen) >= K_target_max:
            break

        lat = float(pvz.iloc[i]["lat"])
        lon = float(pvz.iloc[i]["lon"])

        src = int(nearest_nodes_compat(Gu, X=[lon], Y=[lat])[0])
        if src in pvz_nodes_seen:
            continue
        pvz_nodes_seen.add(src)

        dist = nx.single_source_dijkstra_path_length(
            Gu, source=src, cutoff=MAX_TIME_S, weight="walk_time_s"
        )

        # обновляем best_time только для demand nodes
        for n, d in dist.items():
            idx = node_index.get(int(n), None)
            if idx is None:
                continue
            dd = float(d)
            if dd < best_time[idx]:
                best_time[idx] = dd

        k_now = len(pvz_nodes_seen)
        if k_now in K_set:
            t_sec = np.minimum(best_time, float(MAX_TIME_S))
            t_min = t_sec / 60.0

            mean_min = float(np.sum(t_min * demand_w_list) / total_w)
            p50 = weighted_quantile(t_min, demand_w_list, 0.50)
            p90 = weighted_quantile(t_min, demand_w_list, 0.90)

            share_10 = float(demand_w_list[t_sec <= 600].sum() / total_w)  # 10 минут = 600 сек

            conv = f_time_minutes(t_min)
            D_eff = float(np.sum(demand_w_list * conv))

            results_k.append({
                "K": k_now,
                "share_10min": share_10,
                "mean_time_min": mean_min,
                "p50_time_min": p50,
                "p90_time_min": p90,
                "D_effective": D_eff,
                "D_effective_share": D_eff / total_w if total_w > 0 else np.nan,
                "cap_min": MAX_TIME_S / 60.0,
            })

            print(f"  K={k_now:>3d}: share10={share_10:.4f} mean={mean_min:.1f} p50={p50:.1f} p90={p90:.1f} D={D_eff:,.0f}")

    dfk = pd.DataFrame(results_k).sort_values("K")
    dfk.to_csv(OUT_K, index=False, encoding="utf-8-sig")

    print("[6/6] Transitions + money scenarios ...")
    # переходы между K по соседним точкам из K_LIST (20->30, 30->40, ...)
    transitions = []
    scen_rows = []

    dfk = dfk.set_index("K")
    K_sorted = sorted(K_LIST)

    for a, b in zip(K_sorted[:-1], K_sorted[1:]):
        if a not in dfk.index or b not in dfk.index:
            continue

        Da = float(dfk.loc[a, "D_effective"])
        Db = float(dfk.loc[b, "D_effective"])
        dD = Db - Da

        sa = float(dfk.loc[a, "share_10min"])
        sb = float(dfk.loc[b, "share_10min"])
        ds = sb - sa

        transitions.append({
            "K_from": a,
            "K_to": b,
            "delta_K": b - a,
            "D_from": Da,
            "D_to": Db,
            "delta_D": dD,
            "share10_from": sa,
            "share10_to": sb,
            "delta_share10": ds,
        })

        for sc in SCENARIOS:
            q = float(sc["q"])
            m = float(sc["m"])
            c_fix = float(sc["c_fix"])
            c_open = float(sc["c_open"])

            delta_orders = q * dD
            delta_profit_month = delta_orders * m - (b - a) * c_fix
            payback_months = (b - a) * c_open / delta_profit_month if delta_profit_month > 0 else np.inf

            scen_rows.append({
                "scenario": sc["name"],
                "K_from": a,
                "K_to": b,
                "delta_K": b - a,
                "delta_D": dD,
                "q_orders_per_D": q,
                "margin_per_order_rub": m,
                "fixed_cost_per_pvz_month_rub": c_fix,
                "open_cost_per_pvz_rub": c_open,
                "delta_orders_month": delta_orders,
                "delta_profit_month_rub": delta_profit_month,
                "payback_months": payback_months,
            })

    dft = pd.DataFrame(transitions)
    dft.to_csv(OUT_TR, index=False, encoding="utf-8-sig")

    dfs = pd.DataFrame(scen_rows)
    dfs.to_csv(OUT_SC, index=False, encoding="utf-8-sig")

    t1 = perf_counter()
    print("DONE")
    print("K metrics   :", OUT_K)
    print("Transitions :", OUT_TR)
    print("Scenarios   :", OUT_SC)
    print(f"TOTAL dt={t1 - t0:.1f}s)")


if __name__ == "__main__":
    main()