from time import perf_counter

import geopandas as gpd
import networkx as nx
import osmnx as ox
from pyrosm import OSM


PBF_PATH = r"C:\Users\sgs-w\Downloads\moscow-latest.osm.pbf"  # <-- путь к .pbf
OUT_GRAPHML = r"C:\Users\sgs-w\Downloads\moscow_walk.graphml"
OUT_GPKG = r"C:\Users\sgs-w\Downloads\moscow_walk.gpkg"

WALK_SPEED_MPS = 1.3 


def _ensure_nodes_xy(nodes: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if "geometry" not in nodes.columns or nodes["geometry"].isna().all():
        if {"lon", "lat"}.issubset(nodes.columns):
            nodes = nodes.copy()
            nodes["geometry"] = gpd.points_from_xy(nodes["lon"], nodes["lat"], crs="EPSG:4326")
        elif {"x", "y"}.issubset(nodes.columns):
            nodes = nodes.copy()
            nodes["geometry"] = gpd.points_from_xy(nodes["x"], nodes["y"], crs="EPSG:4326")
        else:
            raise ValueError(
                "nodes без geometry и без (lon,lat)/(x,y). "
                f"Колонки nodes: {list(nodes.columns)}"
            )

    if nodes.crs is None:
        nodes = nodes.set_crs("EPSG:4326", allow_override=True)

    if "x" not in nodes.columns:
        nodes = nodes.copy()
        nodes["x"] = nodes.geometry.x
    if "y" not in nodes.columns:
        nodes = nodes.copy()
        nodes["y"] = nodes.geometry.y

    return nodes


def _ensure_nodes_index(nodes: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    nodes = nodes.copy()
    id_col = None
    for c in ("osmid", "id", "node_id"):
        if c in nodes.columns:
            id_col = c
            break

    if id_col is None:
        nodes.index.name = "osmid"
        return nodes

    nodes = nodes.set_index(id_col, drop=False)
    nodes.index.name = "osmid"
    return nodes


def _ensure_edges_multiindex(edges: gpd.GeoDataFrame, node_index_dtype) -> gpd.GeoDataFrame:
    edges = edges.copy()

    for c in ("u", "v"):
        if c not in edges.columns:
            raise ValueError(f"edges не содержит колонку '{c}'. Колонки edges: {list(edges.columns)}")

    if "key" not in edges.columns:
        edges["key"] = 0

    try:
        edges["u"] = edges["u"].astype(node_index_dtype, copy=False)
        edges["v"] = edges["v"].astype(node_index_dtype, copy=False)
        edges["key"] = edges["key"].astype(int, copy=False)
    except Exception:
        pass

    # drop=True (по умолчанию): u/v/key уходят из колонок в MultiIndex и НЕ конфликтуют с add_edge(key=...)
    edges = edges.set_index(["u", "v", "key"])

    # убрать дубликаты индекса
    edges = edges[~edges.index.duplicated(keep="first")]

    return edges


def _largest_component_compat(G):
    # 1) пробуем официальный путь OSMnx
    try:
        import osmnx.utils_graph as ug  # важно: не ox.utils_graph
        return ug.get_largest_component(G, strongly=False)
    except Exception:
        pass

    # 2) fallback через networkx
    if G.is_directed():
        comps = nx.weakly_connected_components(G)
    else:
        comps = nx.connected_components(G)

    largest_nodes = max(comps, key=len)
    return G.subgraph(largest_nodes).copy()


def _add_edge_lengths_compat(G):
    # OSMnx API менялась: в новых версиях ox.distance.add_edge_lengths
    try:
        import osmnx.distance as od
        return od.add_edge_lengths(G)
    except Exception:
        pass

    # в старых версиях мог быть ox.add_edge_lengths
    if hasattr(ox, "add_edge_lengths"):
        return ox.add_edge_lengths(G)

    raise AttributeError("Не найден add_edge_lengths ни в osmnx.distance, ни в osmnx.")


def main() -> None:
    t0 = perf_counter()
    print("[1/6] Read PBF + extract walking network ...")
    osm = OSM(PBF_PATH)
    nodes, edges = osm.get_network(network_type="walking", nodes=True)
    t1 = perf_counter()
    print(f"  nodes={len(nodes):,} edges={len(edges):,}  (dt={t1 - t0:.1f}s)")

    print("[2/6] Ensure nodes geometry + x/y + index ...")
    nodes = _ensure_nodes_xy(nodes)
    nodes = _ensure_nodes_index(nodes)

    if getattr(edges, "crs", None) is None and getattr(nodes, "crs", None) is not None:
        try:
            edges = edges.set_crs(nodes.crs, allow_override=True)
        except Exception:
            pass

    edges = _ensure_edges_multiindex(edges, nodes.index.dtype)

    t2 = perf_counter()
    print(f"  ok (dt={t2 - t1:.1f}s)")

    print("[3/6] Build graph from GeoDataFrames ...")
    G = ox.graph_from_gdfs(nodes, edges)
    t3 = perf_counter()
    print(f"  G: nodes={len(G.nodes):,} edges={len(G.edges):,}  (dt={t3 - t2:.1f}s)")

    print("[4/6] Keep largest connected component ...")
    G = _largest_component_compat(G)
    t4 = perf_counter()
    print(f"  G_largest: nodes={len(G.nodes):,} edges={len(G.edges):,}  (dt={t4 - t3:.1f}s)")

    print("[5/6] Add edge lengths + walk_time_s ...")
    G = _add_edge_lengths_compat(G)

    for u, v, k, data in G.edges(keys=True, data=True):
        length_m = data.get("length", None)
        if length_m is not None:
            data["walk_time_s"] = float(length_m) / WALK_SPEED_MPS

    t5 = perf_counter()
    print(f"  ok (dt={t5 - t4:.1f}s)")

    print("[6/6] Save GraphML + GeoPackage ...")
    ox.save_graphml(G, OUT_GRAPHML)

    g_nodes, g_edges = ox.graph_to_gdfs(G, nodes=True, edges=True)
    g_nodes.to_file(OUT_GPKG, layer="nodes", driver="GPKG")
    g_edges.to_file(OUT_GPKG, layer="edges", driver="GPKG")

    t6 = perf_counter()
    print(f"Saved:\n  {OUT_GRAPHML}\n  {OUT_GPKG}")
    print(f"TOTAL dt={t6 - t0:.1f}s")


if __name__ == "__main__":
    main()
