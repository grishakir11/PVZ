# 12_eval_k_scenarios_share10_by_district.py
# Считает по районам долю спроса (demand_w), покрытого выбранными ПВЗ в пределах 10 минут пешком.
# Делает это для нескольких K, используя pvz_selected_kmax.csv (ранжированный список точек 1..Kmax).
#
# Вход:
#   - pvz_project/demand_points.gpkg (layer: demand_points)  (district_name, demand_w)
#   - pvz_project/pvz_selected_kmax.csv  (sel_rank, lat, lon)
#   - moscow_walk.graphml
#
# Выход:
#   - pvz_project/k_scenarios_share10_by_district.csv
#   - pvz_project/k_scenarios_share10_city.csv

from pathlib import Path
import math
from time import perf_counter

import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
import osmnx as ox


# ====== SETTINGS ======
PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

DEMAND_GPKG = PROJECT_DIR / "demand_points.gpkg"
DEMAND_LAYER = "demand_points"

PVZ_RANKED_CSV = PROJECT_DIR / "pvz_selected_kmax.csv"  # из 11 скрипта

GRAPHML = Path(r"C:\Users\sgs-w\Downloads\moscow_walk.graphml")

OUT_DIST_CSV = PROJECT_DIR / "k_scenarios_share10_by_district.csv"
OUT_CITY_CSV = PROJECT_DIR / "k_scenarios_share10_city.csv"

WGS84 = "EPSG:4326"
METRIC_CRS = "EPSG:32637"

K_LIST = [20, 30, 40, 60]
WALK_TIME_CUTOFF_S = 600
WALK_SPEED_MPS = 1.3
# =====================


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


def main():
    t0 = perf_counter()

    print("[1/6] Load demand points ...")
    demand = gpd.read_file(DEMAND_GPKG, layer=DEMAND_LAYER)
    if demand.crs is None:
        demand = demand.set_crs(METRIC_CRS, allow_override=True)
    demand_wgs = demand.to_crs(WGS84)

    if "district_name" not in demand.columns or "demand_w" not in demand.columns:
        raise RuntimeError("В demand_points должны быть district_name и demand_w.")

    print(f"  demand_points={len(demand):,} total_demand_w={demand['demand_w'].sum():,.0f}")

    print("[2/6] Load ranked PVZ list ...")
    pvz = pd.read_csv(PVZ_RANKED_CSV, encoding="utf-8-sig")
    need = {"sel_rank", "lat", "lon"}
    if not need.issubset(pvz.columns):
        raise RuntimeError(f"pvz_selected_kmax.csv должен иметь {need}.")
    pvz = pvz.sort_values("sel_rank").reset_index(drop=True)

    kmax = int(pvz["sel_rank"].max())
    if max(K_LIST) > kmax:
        raise RuntimeError(f"K_LIST содержит K>{kmax}. Увеличь Kmax в 11 скрипте и пересчитай.")

    print(f"  pvz_ranked_count={len(pvz)} (kmax={kmax})")

    print("[3/6] Load graph ...")
    G = load_graphml_robust(GRAPHML)
    G = ensure_walk_time(G)
    Gu = to_undirected_compat(G)
    print(f"  G nodes={len(Gu.nodes):,} edges={len(Gu.edges):,}")

    print("[4/6] Snap demand nodes once ...")
    demand_nodes = nearest_nodes_compat(Gu, X=demand_wgs.geometry.x.values, Y=demand_wgs.geometry.y.values)

    demand_df = pd.DataFrame({
        "district_name": demand["district_name"].astype(str).values,
        "demand_w": demand["demand_w"].astype(float).values,
        "node": np.array([int(x) for x in demand_nodes], dtype=np.int64),
    })

    # totals
    dist_total = demand_df.groupby("district_name")["demand_w"].sum()
    total_demand = float(demand_df["demand_w"].sum())

    print("[5/6] For each K: compute covered demand via union of <=10min balls ...")
    results = []
    city_rows = []

    # cache dijkstra balls for pvz nodes (по рангу)
    pvz_nodes_cache = {}

    for K in K_LIST:
        pvz_k = pvz.head(K).copy()
        pvz_k_gdf = gpd.GeoDataFrame(
            pvz_k,
            geometry=gpd.points_from_xy(pvz_k["lon"], pvz_k["lat"], crs=WGS84),
            crs=WGS84,
        )
        pvz_nodes = nearest_nodes_compat(Gu, X=pvz_k_gdf.geometry.x.values, Y=pvz_k_gdf.geometry.y.values)
        pvz_nodes = [int(x) for x in pvz_nodes]

        covered_nodes = set()
        for idx, src in enumerate(pvz_nodes):
            key = (K, idx)  # локально, но лучше по sel_rank
            # кэш по src: dijkstra ball <=600s
            if src in pvz_nodes_cache:
                ball = pvz_nodes_cache[src]
            else:
                dist = nx.single_source_dijkstra_path_length(
                    Gu, source=src, cutoff=WALK_TIME_CUTOFF_S, weight="walk_time_s"
                )
                ball = set(dist.keys())
                pvz_nodes_cache[src] = ball
            covered_nodes |= ball

        covered_mask = demand_df["node"].isin(covered_nodes)
        covered_by_dist = demand_df.loc[covered_mask].groupby("district_name")["demand_w"].sum()

        out = pd.DataFrame({
            "district_name": dist_total.index,
            f"covered_w_k{K}": covered_by_dist.reindex(dist_total.index).fillna(0.0).values,
            f"total_w": dist_total.values,
        })
        out[f"share_10min_k{K}"] = np.where(out["total_w"] > 0, out[f"covered_w_k{K}"] / out["total_w"], np.nan)

        results.append(out[["district_name", f"covered_w_k{K}", f"share_10min_k{K}"]])

        covered_city = float(out[f"covered_w_k{K}"].sum())
        city_rows.append({
            "K": K,
            "covered_demand_w_10min": covered_city,
            "total_demand_w": total_demand,
            "share_10min": covered_city / total_demand if total_demand > 0 else np.nan,
        })

        print(f"  K={K}: city_share_10min={city_rows[-1]['share_10min']:.4f}")

    print("[6/6] Save ...")
    # merge district tables
    base = pd.DataFrame({"district_name": dist_total.index, "total_w": dist_total.values})
    for r in results:
        base = base.merge(r, on="district_name", how="left")

    # добавить deltas для удобства
    if 20 in K_LIST and 30 in K_LIST:
        base["delta_share_30_minus_20"] = base["share_10min_k30"] - base["share_10min_k20"]
    if 20 in K_LIST and 40 in K_LIST:
        base["delta_share_40_minus_20"] = base["share_10min_k40"] - base["share_10min_k20"]

    base.to_csv(OUT_DIST_CSV, index=False, encoding="utf-8-sig")
    pd.DataFrame(city_rows).to_csv(OUT_CITY_CSV, index=False, encoding="utf-8-sig")

    t1 = perf_counter()
    print("DONE")
    print("DIST:", OUT_DIST_CSV)
    print("CITY:", OUT_CITY_CSV)
    print(f"TOTAL dt={t1 - t0:.1f}s)")


if __name__ == "__main__":
    main()
