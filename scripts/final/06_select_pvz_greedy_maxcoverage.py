# 06_select_pvz_greedy_maxcoverage.py
# Выбирает K=20 кандидатов ПВЗ, максимизируя покрытый спрос в пределах WALK_TIME_CUTOFF_S по walking graph.
# Модель: Max Coverage, greedy (каждый шаг выбирает кандидата с максимальным приростом покрытия).
#
# Вход:
#   - pvz_project/demand_points.gpkg (layer: demand_points)  или demand_points.csv
#   - pvz_project/candidate_points.gpkg (layer: candidate_points) или candidate_points.csv
#   - moscow_walk.graphml
#
# Выход:
#   - pvz_project/pvz_selected_20.csv
#   - pvz_project/pvz_selected_20.gpkg (layer: pvz_selected_20)
#   - pvz_project/pvz_coverage_report.txt

from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
import osmnx as ox


# ====== НАСТРОЙКИ ======
PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

DEMAND_GPKG = PROJECT_DIR / "demand_points.gpkg"
DEMAND_LAYER = "demand_points"
DEMAND_CSV = PROJECT_DIR / "demand_points.csv"

CAND_GPKG = PROJECT_DIR / "candidate_points.gpkg"
CAND_LAYER = "candidate_points"
CAND_CSV = PROJECT_DIR / "candidate_points.csv"

GRAPHML = Path(r"C:\Users\sgs-w\Downloads\moscow_walk.graphml")

OUT_CSV = PROJECT_DIR / "pvz_selected_20.csv"
OUT_GPKG = PROJECT_DIR / "pvz_selected_20.gpkg"
OUT_LAYER = "pvz_selected_20"
OUT_REPORT = PROJECT_DIR / "pvz_coverage_report.txt"

METRIC_CRS = "EPSG:32637"
WGS84 = "EPSG:4326"

K = 20                      # сколько ПВЗ выбрать
WALK_TIME_CUTOFF_S = 600    # порог покрытия по графу (10 мин)

# Предфильтр кандидатов по евклидовой близости к спросу (ускорение)
EUCLIDEAN_BUFFER_M = 1100   # грубо соответствует 10 минут пешком
MAX_CANDIDATES = 4000       # если кандидатов слишком много, оставим топ по локальному спросу

WALK_SPEED_MPS = 1.3        # если в графе нет walk_time_s, восстановим
# =======================


def add_edge_lengths_compat(G):
    try:
        import osmnx.distance as od
        return od.add_edge_lengths(G)
    except Exception:
        pass
    if hasattr(ox, "add_edge_lengths"):
        return ox.add_edge_lengths(G)
    raise AttributeError("Не найден add_edge_lengths ни в osmnx.distance, ни в osmnx.")


def _iter_edges(G):
    if isinstance(G, (nx.MultiGraph, nx.MultiDiGraph)):
        for u, v, k, data in G.edges(keys=True, data=True):
            yield u, v, k, data
    else:
        for u, v, data in G.edges(data=True):
            yield u, v, None, data


def load_graphml_robust(path: Path):
    # 1) пробуем штатно
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

    # crs
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

    # length/walk_time -> float, oneway yes/no -> bool (чтобы не было мусора)
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


def ensure_walk_time(G):
    any_edge = None
    for _, _, _, data in _iter_edges(G):
        any_edge = data
        break
    if any_edge is None:
        raise RuntimeError("Граф пустой (нет рёбер).")

    if "walk_time_s" in any_edge:
        # на всякий: привести тип
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
    raise AttributeError("Не найден nearest_nodes в установленной версии osmnx.")


def load_points():
    # demand
    if DEMAND_GPKG.exists():
        demand = gpd.read_file(DEMAND_GPKG, layer=DEMAND_LAYER)
        if demand.crs is None:
            demand = demand.set_crs(METRIC_CRS, allow_override=True)
    else:
        df = pd.read_csv(DEMAND_CSV, encoding="utf-8-sig")
        demand = gpd.GeoDataFrame(
            df,
            geometry=gpd.points_from_xy(df["lon"], df["lat"], crs=WGS84),
        ).to_crs(METRIC_CRS)

    if "demand_w" not in demand.columns:
        raise RuntimeError("В demand нет колонки demand_w.")

    # candidates
    if CAND_GPKG.exists():
        cand = gpd.read_file(CAND_GPKG, layer=CAND_LAYER)
        if cand.crs is None:
            cand = cand.set_crs(METRIC_CRS, allow_override=True)
    else:
        df = pd.read_csv(CAND_CSV, encoding="utf-8-sig")
        cand = gpd.GeoDataFrame(
            df,
            geometry=gpd.points_from_xy(df["lon"], df["lat"], crs=WGS84),
        ).to_crs(METRIC_CRS)

    return demand, cand


def prefilter_candidates_by_euclidean(demand_m: gpd.GeoDataFrame, cand_m: gpd.GeoDataFrame):
    # Быстро отсечь кандидатов, у которых в радиусе нет спроса
    cand_buf = cand_m.copy()
    cand_buf["geometry"] = cand_buf.geometry.buffer(EUCLIDEAN_BUFFER_M)

    # demand points внутри буфера кандидата
    joined = gpd.sjoin(
        demand_m[["demand_w", "geometry"]],
        cand_buf[["geometry"]],
        predicate="within",
        how="inner",
    )
    # joined.index_right -> индексы cand_buf
    local = joined.groupby("index_right")["demand_w"].sum()

    cand_m = cand_m.copy()
    cand_m["local_demand_w"] = cand_m.index.map(local).fillna(0).astype(int)
    cand_m = cand_m[cand_m["local_demand_w"] > 0].copy()

    # если всё равно слишком много — оставим top по локальному спросу
    if len(cand_m) > MAX_CANDIDATES:
        cand_m = cand_m.sort_values("local_demand_w", ascending=False).head(MAX_CANDIDATES).copy()

    return cand_m


def main():
    t0 = perf_counter()

    print("[1/7] Load demand + candidate points ...")
    demand_m, cand_m = load_points()
    demand_m = demand_m.to_crs(METRIC_CRS)
    cand_m = cand_m.to_crs(METRIC_CRS)

    total_demand = int(demand_m["demand_w"].sum())
    print(f"  demand_points={len(demand_m):,} total_demand_w={total_demand:,}")
    print(f"  candidates_raw={len(cand_m):,}")

    print("[2/7] Prefilter candidates by euclidean buffer ...")
    cand_m = prefilter_candidates_by_euclidean(demand_m, cand_m)
    print(f"  candidates_after_prefilter={len(cand_m):,}")

    t1 = perf_counter()
    print(f"  ok (dt={t1 - t0:.1f}s)")

    print("[3/7] Load graph ...")
    G = load_graphml_robust(GRAPHML)
    G = ensure_walk_time(G)
    Gu = to_undirected_compat(G)
    print(f"  G nodes={len(Gu.nodes):,} edges={len(Gu.edges):,}")

    t2 = perf_counter()
    print(f"  ok (dt={t2 - t1:.1f}s)")

    print("[4/7] Map demand/candidates to nearest graph nodes ...")
    demand_wgs = demand_m.to_crs(WGS84)
    cand_wgs = cand_m.to_crs(WGS84)

    demand_nodes = nearest_nodes_compat(Gu, X=demand_wgs.geometry.x.values, Y=demand_wgs.geometry.y.values)
    cand_nodes = nearest_nodes_compat(Gu, X=cand_wgs.geometry.x.values, Y=cand_wgs.geometry.y.values)

    demand_m = demand_m.copy()
    cand_m = cand_m.copy()
    demand_m["node"] = demand_nodes
    cand_m["node"] = cand_nodes

    # агрегируем спрос по узлам (если несколько demand точек попали в один node)
    node_weight = {}
    for n, w in zip(demand_m["node"].values, demand_m["demand_w"].values):
        node_weight[int(n)] = node_weight.get(int(n), 0) + int(w)
    demand_nodes_set = set(node_weight.keys())

    t3 = perf_counter()
    print(f"  demand_nodes_unique={len(demand_nodes_set):,} (dt={t3 - t2:.1f}s)")

    print("[5/7] Precompute coverage sets for each candidate (Dijkstra cutoff) ...")
    # coverage_list[i] = список узлов спроса, которые покрывает кандидат i
    # coverage_w[i] = суммарный вес покрываемого спроса (если бы всё было непокрыто)
    coverage_list = []
    coverage_w = []

    cand_node_list = [int(n) for n in cand_m["node"].values]

    for i, src in enumerate(cand_node_list):
        dist = nx.single_source_dijkstra_path_length(
            Gu,
            source=src,
            cutoff=WALK_TIME_CUTOFF_S,
            weight="walk_time_s",
        )

        # пересечение с demand nodes
        covered_nodes = [n for n in dist.keys() if n in demand_nodes_set]
        w = 0
        for n in covered_nodes:
            w += node_weight[n]

        coverage_list.append(covered_nodes)
        coverage_w.append(int(w))

        if (i + 1) % 200 == 0:
            print(f"  processed {i+1}/{len(cand_node_list)} candidates")

    t4 = perf_counter()
    print(f"  ok (dt={t4 - t3:.1f}s)")

    print("[6/7] Greedy selection ...")
    uncovered = dict(node_weight)  # node->weight, удаляем когда покрыли
    selected_idx = []
    selected_gain = []
    cumulative_cov = 0

    for step in range(K):
        best_i = None
        best_gain = -1

        # полный перебор кандидатов по приросту
        for i, cov_nodes in enumerate(coverage_list):
            if i in selected_idx:
                continue
            gain = 0
            for n in cov_nodes:
                gain += uncovered.get(n, 0)
            if gain > best_gain:
                best_gain = gain
                best_i = i

        if best_i is None or best_gain <= 0:
            print(f"  stop at step={step+1}: no positive gain")
            break

        selected_idx.append(best_i)
        selected_gain.append(int(best_gain))

        # обновить uncovered
        for n in coverage_list[best_i]:
            if n in uncovered:
                cumulative_cov += uncovered[n]
                del uncovered[n]

        print(f"  step {step+1:02d}/{K}: gain={best_gain:,} cum_covered={cumulative_cov:,} ({cumulative_cov/total_demand:.3f})")

    t5 = perf_counter()
    print(f"  ok (dt={t5 - t4:.1f}s)")

    print("[7/7] Save results ...")
    sel = cand_m.iloc[selected_idx].copy()
    sel["sel_rank"] = np.arange(1, len(sel) + 1)
    sel["gain_demand_w"] = selected_gain
    sel["covered_cum_w"] = np.cumsum(selected_gain)
    sel["covered_cum_share"] = sel["covered_cum_w"] / float(total_demand)

    # сохранить
    sel_wgs = sel.to_crs(WGS84)
    out_df = pd.DataFrame({
        "sel_rank": sel_wgs["sel_rank"].astype(int),
        "district_name": sel_wgs.get("district_name", "").astype(str),
        "lat": sel_wgs.geometry.y.astype(float),
        "lon": sel_wgs.geometry.x.astype(float),
        "gain_demand_w": sel_wgs["gain_demand_w"].astype(int),
        "covered_cum_w": sel_wgs["covered_cum_w"].astype(int),
        "covered_cum_share": sel_wgs["covered_cum_share"].astype(float),
    })
    out_df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    sel.to_file(OUT_GPKG, layer=OUT_LAYER, driver="GPKG")

    report = (
        f"K={K}\n"
        f"WALK_TIME_CUTOFF_S={WALK_TIME_CUTOFF_S}\n"
        f"EUCLIDEAN_BUFFER_M={EUCLIDEAN_BUFFER_M}\n"
        f"candidates_used={len(cand_m)}\n"
        f"demand_points={len(demand_m)}\n"
        f"total_demand_w={total_demand}\n"
        f"covered_demand_w={sum(selected_gain)}\n"
        f"covered_share={sum(selected_gain)/float(total_demand):.6f}\n"
        f"selected_count={len(sel)}\n"
    )
    OUT_REPORT.write_text(report, encoding="utf-8")

    t6 = perf_counter()
    print("DONE")
    print("CSV   :", OUT_CSV)
    print("GPKG  :", OUT_GPKG)
    print("REPORT:", OUT_REPORT)
    print(f"TOTAL dt={t6 - t0:.1f}s)")


if __name__ == "__main__":
    main()

