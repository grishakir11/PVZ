# 02b_add_walk_metrics_multipoint.py
# Устойчивые walk/metro метрики по нескольким точкам внутри каждого полигона.

from pathlib import Path
import random
from time import perf_counter

import numpy as np
import geopandas as gpd
import networkx as nx
import osmnx as ox
from shapely.geometry import Point

PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

IN_GPKG = PROJECT_DIR / "district_features.gpkg"
IN_LAYER_DISTRICTS = "districts_features"
IN_LAYER_METRO = "metro_osm"

GRAPHML = Path(r"C:\Users\sgs-w\Downloads\moscow_walk.graphml")

OUT_GPKG = PROJECT_DIR / "district_features_walk_mp.gpkg"
OUT_LAYER = "districts_features_walk_mp"
OUT_CSV = PROJECT_DIR / "district_features_walk_mp.csv"

METRIC_CRS = "EPSG:32637"
WGS84 = "EPSG:4326"

WALK_SPEED_MPS = 1.3
WALK_TIME_CUTOFF_S = 600

N_RANDOM_POINTS = 8   # сколько случайных точек в полигоне + 1 representative_point
RNG_SEED = 42


def add_edge_lengths_compat(G):
    try:
        import osmnx.distance as od
        return od.add_edge_lengths(G)
    except Exception:
        pass
    if hasattr(ox, "add_edge_lengths"):
        return ox.add_edge_lengths(G)
    raise AttributeError("Не найден add_edge_lengths.")


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

        # узлы после read_graphml часто строковые
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

        # x/y в float
        for n, data in G.nodes(data=True):
            if "x" in data:
                try: data["x"] = float(data["x"])
                except Exception: pass
            if "y" in data:
                try: data["y"] = float(data["y"])
                except Exception: pass

        # walk_time/length в float
        for _, _, _, data in _iter_edges(G):
            if "walk_time_s" in data:
                try: data["walk_time_s"] = float(data["walk_time_s"])
                except Exception: pass
            if "length" in data:
                try: data["length"] = float(data["length"])
                except Exception: pass

        return G


def ensure_walk_time(G):
    any_edge = None
    for _, _, _, data in _iter_edges(G):
        any_edge = data
        break
    if any_edge is None:
        raise RuntimeError("Граф пустой.")

    if "walk_time_s" in any_edge:
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


def random_points_in_polygon(poly, n, rng):
    minx, miny, maxx, maxy = poly.bounds
    pts = []
    tries = 0
    # ограничение по попыткам чтобы не зависнуть на странной геометрии
    while len(pts) < n and tries < n * 500:
        tries += 1
        p = Point(rng.uniform(minx, maxx), rng.uniform(miny, maxy))
        if poly.contains(p):
            pts.append(p)
    return pts


def main():
    rng = random.Random(RNG_SEED)
    t0 = perf_counter()

    print("[1/6] Load polygons + metro ...")
    districts = gpd.read_file(IN_GPKG, layer=IN_LAYER_DISTRICTS)
    if districts.crs is None:
        districts = districts.set_crs(METRIC_CRS, allow_override=True)

    try:
        metro = gpd.read_file(IN_GPKG, layer=IN_LAYER_METRO)
        if metro.crs is None:
            metro = metro.set_crs(METRIC_CRS, allow_override=True)
    except Exception:
        metro = gpd.GeoDataFrame(geometry=[], crs=METRIC_CRS)

    districts_m = districts.to_crs(METRIC_CRS).copy()

    t1 = perf_counter()
    print(f"  polygons={len(districts_m):,} metro={len(metro):,} (dt={t1 - t0:.1f}s)")

    print("[2/6] Load graph ...")
    G = load_graphml_robust(GRAPHML)
    G = ensure_walk_time(G)
    Gu = to_undirected_compat(G)

    t2 = perf_counter()
    print(f"  G nodes={len(Gu.nodes):,} edges={len(Gu.edges):,} (dt={t2 - t1:.1f}s)")

    print("[3/6] Precompute dist_to_metro ...")
    if len(metro) > 0:
        metro_wgs = metro.to_crs(WGS84)
        metro_wgs = metro_wgs[metro_wgs.geometry.type.isin(["Point", "MultiPoint"])].copy()
        if len(metro_wgs) > 0:
            metro_nodes = nearest_nodes_compat(Gu, X=metro_wgs.geometry.x.values, Y=metro_wgs.geometry.y.values)
            metro_nodes = list(set(metro_nodes))
            dist_to_metro = nx.multi_source_dijkstra_path_length(Gu, sources=metro_nodes, weight="walk_time_s")
        else:
            dist_to_metro = {}
    else:
        dist_to_metro = {}

    t3 = perf_counter()
    print(f"  ok (dt={t3 - t2:.1f}s)")

    print("[4/6] Compute multipoint metrics ...")
    walk_reach_p50 = []
    metro_time_p10 = []

    for poly in districts_m.geometry:
        pts = [poly.representative_point()]
        pts += random_points_in_polygon(poly, N_RANDOM_POINTS, rng)

        # в WGS84 для nearest_nodes
        pts_wgs = gpd.GeoSeries(pts, crs=METRIC_CRS).to_crs(WGS84)
        nodes = nearest_nodes_compat(Gu, X=pts_wgs.x.values, Y=pts_wgs.y.values)

        reach_vals = []
        metro_vals = []

        for n in nodes:
            d = nx.single_source_dijkstra_path_length(
                Gu, source=n, cutoff=WALK_TIME_CUTOFF_S, weight="walk_time_s"
            )
            reach_vals.append(len(d))

            mt = dist_to_metro.get(n, np.nan)
            metro_vals.append(mt)

        walk_reach_p50.append(float(np.nanmedian(reach_vals)))
        metro_time_p10.append(float(np.nanpercentile(metro_vals, 10)) if np.isfinite(metro_vals).any() else np.nan)

    districts_m["walk_reach_nodes_10min_p50"] = walk_reach_p50
    districts_m["metro_walk_time_s_p10"] = metro_time_p10

    t4 = perf_counter()
    print(f"  ok (dt={t4 - t3:.1f}s)")

    print("[5/6] Save ...")
    districts_m.to_file(OUT_GPKG, layer=OUT_LAYER, driver="GPKG")
    districts_m.drop(columns=["geometry"], errors="ignore").to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    t5 = perf_counter()
    print("DONE")
    print("CSV :", OUT_CSV)
    print("GPKG:", OUT_GPKG)
    print(f"TOTAL dt={t5 - t0:.1f}s)")


if __name__ == "__main__":
    main()
