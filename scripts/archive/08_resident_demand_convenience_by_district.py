# 08_resident_demand_convenience_by_district.py
# Считает спрос жителей и удобство для жителей "от дома до ближайшего ПВЗ" по walking graph.
#
# Вход:
#   - pvz_project/district_index_v2.gpkg (layer: districts_index_v2)  (полигоны + district_name)
#   - pvz_project/demand_points.gpkg (layer: demand_points)          (точки спроса, demand_w, district_name)
#   - pvz_project/pvz_selected_20.gpkg (layer: pvz_selected_20)      (выбранные ПВЗ)
#   - moscow_walk.graphml
#
# Выход:
#   - pvz_project/district_resident_metrics.csv
#   - pvz_project/district_resident_metrics.gpkg (layer: district_resident_metrics)

from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
import osmnx as ox


# ====== PATHS ======
PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

DIST_GPKG = PROJECT_DIR / "district_index_v2.gpkg"
DIST_LAYER = "districts_index_v2"

DEMAND_GPKG = PROJECT_DIR / "demand_points.gpkg"
DEMAND_LAYER = "demand_points"

PVZ_GPKG = PROJECT_DIR / "pvz_selected_20.gpkg"
PVZ_LAYER = "pvz_selected_20"

GRAPHML = Path(r"C:\Users\sgs-w\Downloads\moscow_walk.graphml")

OUT_CSV = PROJECT_DIR / "district_resident_metrics.csv"
OUT_GPKG = PROJECT_DIR / "district_resident_metrics.gpkg"
OUT_LAYER = "district_resident_metrics"

METRIC_CRS = "EPSG:32637"
WGS84 = "EPSG:4326"

WALK_SPEED_MPS = 1.3  # если нет walk_time_s
# ====================


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
    cutoff = q * cw[-1]
    return v[np.searchsorted(cw, cutoff, side="left")]


def compute_group_metrics(times_min, weights):
    times_min = np.asarray(times_min, dtype=float)
    weights = np.asarray(weights, dtype=float)
    m = np.isfinite(times_min) & np.isfinite(weights) & (weights > 0)
    if m.sum() == 0:
        return {
            "mean_time_min": np.nan,
            "p50_time_min": np.nan,
            "p90_time_min": np.nan,
            "share_5min": np.nan,
            "share_10min": np.nan,
            "share_15min": np.nan,
        }
    t = times_min[m]
    w = weights[m]
    wsum = w.sum()

    mean = float((t * w).sum() / wsum)
    p50 = float(weighted_quantile(t, w, 0.50))
    p90 = float(weighted_quantile(t, w, 0.90))

    share_5 = float(w[t <= 5].sum() / wsum)
    share_10 = float(w[t <= 10].sum() / wsum)
    share_15 = float(w[t <= 15].sum() / wsum)

    return {
        "mean_time_min": mean,
        "p50_time_min": p50,
        "p90_time_min": p90,
        "share_5min": share_5,
        "share_10min": share_10,
        "share_15min": share_15,
    }


def main():
    print("[1/6] Load districts + demand + pvz ...")
    districts = gpd.read_file(DIST_GPKG, layer=DIST_LAYER)
    if districts.crs is None:
        districts = districts.set_crs(METRIC_CRS, allow_override=True)
    districts_m = districts.to_crs(METRIC_CRS)

    demand = gpd.read_file(DEMAND_GPKG, layer=DEMAND_LAYER)
    if demand.crs is None:
        demand = demand.set_crs(METRIC_CRS, allow_override=True)
    demand_m = demand.to_crs(METRIC_CRS)

    pvz = gpd.read_file(PVZ_GPKG, layer=PVZ_LAYER)
    if pvz.crs is None:
        pvz = pvz.set_crs(METRIC_CRS, allow_override=True)
    pvz_m = pvz.to_crs(METRIC_CRS)

    if "district_name" not in demand_m.columns:
        raise RuntimeError("В demand_points нет district_name.")
    if "demand_w" not in demand_m.columns:
        raise RuntimeError("В demand_points нет demand_w.")

    print(f"  districts={len(districts_m):,} demand_points={len(demand_m):,} pvz={len(pvz_m):,}")

    print("[2/6] Load graph + walk_time ...")
    G = load_graphml_robust(GRAPHML)
    G = ensure_walk_time(G)
    Gu = to_undirected_compat(G)
    print(f"  G nodes={len(Gu.nodes):,} edges={len(Gu.edges):,}")

    print("[3/6] Map demand/pvz to nearest nodes ...")
    demand_wgs = demand_m.to_crs(WGS84)
    pvz_wgs = pvz_m.to_crs(WGS84)

    demand_nodes = nearest_nodes_compat(Gu, X=demand_wgs.geometry.x.values, Y=demand_wgs.geometry.y.values)
    pvz_nodes = nearest_nodes_compat(Gu, X=pvz_wgs.geometry.x.values, Y=pvz_wgs.geometry.y.values)
    pvz_nodes = list(set(int(x) for x in pvz_nodes))

    demand_df = pd.DataFrame({
        "district_name": demand_m["district_name"].astype(str).values,
        "demand_w": demand_m["demand_w"].astype(float).values,
        "node": np.array([int(x) for x in demand_nodes], dtype=np.int64),
    })

    print("[4/6] Multi-source Dijkstra: time to nearest PVZ ...")
    dist_to_pvz = nx.multi_source_dijkstra_path_length(Gu, sources=pvz_nodes, weight="walk_time_s")

    t_s = np.array([dist_to_pvz.get(int(n), np.nan) for n in demand_df["node"].values], dtype=float)
    demand_df["time_to_pvz_min"] = t_s / 60.0

    print("[5/6] Aggregate by district: demand + convenience ...")
    out_rows = []
    for name, g in demand_df.groupby("district_name", sort=False):
        demand_total = float(np.nansum(g["demand_w"].values))
        m = compute_group_metrics(g["time_to_pvz_min"].values, g["demand_w"].values)
        row = {"district_name": name, "demand_total": demand_total}
        row.update(m)
        out_rows.append(row)

    agg = pd.DataFrame(out_rows)
    merged = districts_m.merge(agg, on="district_name", how="left")

    city = compute_group_metrics(demand_df["time_to_pvz_min"].values, demand_df["demand_w"].values)
    city_demand = float(np.nansum(demand_df["demand_w"].values))

    print("CITY TOTAL DEMAND:", f"{city_demand:,.0f}")
    print("CITY mean_time_min:", city["mean_time_min"])
    print("CITY p50_time_min :", city["p50_time_min"])
    print("CITY share_10min  :", city["share_10min"])

    print("[6/6] Save ...")
    agg.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    merged.to_file(OUT_GPKG, layer=OUT_LAYER, driver="GPKG")

    print("DONE")
    print("CSV :", OUT_CSV)
    print("GPKG:", OUT_GPKG)


if __name__ == "__main__":
    main()
