# 02_add_walk_metrics.py
# Добавляет walk-метрики к полигонам из district_features.gpkg, используя moscow_walk.graphml.
# Вход:
#   - pvz_project/district_features.gpkg (layer: districts_features, optional: metro_osm)
#   - moscow_walk.graphml
# Выход:
#   - pvz_project/district_features_walk.csv
#   - pvz_project/district_features_walk.gpkg (layer: districts_features_walk)

from pathlib import Path
from time import perf_counter

import geopandas as gpd
import networkx as nx
import osmnx as ox


# ====== НАСТРОЙКИ ======
PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

IN_GPKG = PROJECT_DIR / "district_features.gpkg"
IN_LAYER_DISTRICTS = "districts_features"
IN_LAYER_METRO = "metro_osm"  # может отсутствовать

GRAPHML = Path(r"C:\Users\sgs-w\Downloads\moscow_walk.graphml")

OUT_GPKG = PROJECT_DIR / "district_features_walk.gpkg"
OUT_LAYER = "districts_features_walk"
OUT_CSV = PROJECT_DIR / "district_features_walk.csv"

METRIC_CRS = "EPSG:32637"
WGS84 = "EPSG:4326"

WALK_SPEED_MPS = 1.3
WALK_TIME_CUTOFF_S = 600
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
    # единый итератор рёбер для MultiGraph и обычных графов
    if isinstance(G, (nx.MultiGraph, nx.MultiDiGraph)):
        for u, v, k, data in G.edges(keys=True, data=True):
            yield u, v, k, data
    else:
        for u, v, data in G.edges(data=True):
            yield u, v, None, data


def _coerce_nodes_xy(G):
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


def _coerce_edge_floats(G):
    for u, v, k, data in _iter_edges(G):
        if "walk_time_s" in data:
            try:
                data["walk_time_s"] = float(data["walk_time_s"])
            except Exception:
                pass
        if "length" in data:
            try:
                data["length"] = float(data["length"])
            except Exception:
                pass


def _fix_oneway(G):
    # только чтобы не было мусора, если вдруг дальше захочешь directed анализ
    for u, v, k, data in _iter_edges(G):
        if "oneway" in data and isinstance(data["oneway"], str):
            s = data["oneway"].strip().lower()
            if s in ("yes", "true", "1"):
                data["oneway"] = True
            elif s in ("no", "false", "0"):
                data["oneway"] = False
            # иначе оставляем как есть


def load_graphml_robust(path: Path):
    # 1) пробуем штатно
    try:
        return ox.load_graphml(path)
    except Exception as e:
        print(f"  ox.load_graphml failed: {e}")
        print("  fallback: networkx.read_graphml ...")

    # 2) fallback без агрессивной конвертации типов
    G = nx.read_graphml(path)

    # узлы после read_graphml часто строковые — приводим к int где возможно
    mapping = {}
    for n in list(G.nodes):
        if isinstance(n, str):
            try:
                mapping[n] = int(n)
            except Exception:
                pass
    if mapping:
        G = nx.relabel_nodes(G, mapping, copy=True)

    # crs иногда теряется/переименовывается
    if "crs" not in G.graph:
        # OSMnx обычно использует EPSG:4326
        G.graph["crs"] = "epsg:4326"

    _coerce_nodes_xy(G)
    _coerce_edge_floats(G)
    _fix_oneway(G)

    return G


def ensure_walk_time(G):
    # если walk_time_s уже есть — просто гарантируем тип float
    any_edge = None
    for _, _, _, data in _iter_edges(G):
        any_edge = data
        break

    if any_edge is None:
        raise RuntimeError("Граф пустой (нет рёбер).")

    if "walk_time_s" in any_edge:
        _coerce_edge_floats(G)
        return G

    # если нет — восстановим из length
    G = add_edge_lengths_compat(G)
    for u, v, k, data in _iter_edges(G):
        if "length" in data:
            data["walk_time_s"] = float(data["length"]) / WALK_SPEED_MPS

    _coerce_edge_floats(G)
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


def main():
    t0 = perf_counter()

    print("[1/6] Load polygons + метро ...")
    districts = gpd.read_file(IN_GPKG, layer=IN_LAYER_DISTRICTS)
    if districts.crs is None:
        districts = districts.set_crs(METRIC_CRS, allow_override=True)

    try:
        metro = gpd.read_file(IN_GPKG, layer=IN_LAYER_METRO)
        if metro.crs is None:
            metro = metro.set_crs(METRIC_CRS, allow_override=True)
    except Exception:
        metro = gpd.GeoDataFrame(geometry=[], crs=METRIC_CRS)

    t1 = perf_counter()
    print(f"  polygons={len(districts):,} metro={len(metro):,} (dt={t1 - t0:.1f}s)")

    print("[2/6] Load graph (robust) ...")
    G = load_graphml_robust(GRAPHML)
    G = ensure_walk_time(G)
    Gu = to_undirected_compat(G)

    t2 = perf_counter()
    print(f"  G nodes={len(Gu.nodes):,} edges={len(Gu.edges):,} (dt={t2 - t1:.1f}s)")

    print("[3/6] Polygon inside-point -> nearest nodes ...")
    districts_m = districts.to_crs(METRIC_CRS).copy()
    inside_pt_m = districts_m.geometry.representative_point()
    inside_pt_wgs = gpd.GeoSeries(inside_pt_m, crs=METRIC_CRS).to_crs(WGS84)

    src_nodes = nearest_nodes_compat(Gu, X=inside_pt_wgs.x.values, Y=inside_pt_wgs.y.values)

    t3 = perf_counter()
    print(f"  ok (dt={t3 - t2:.1f}s)")

    print("[4/6] walk_reach_nodes_10min_point ...")
    reach_counts = []
    for src in src_nodes:
        d = nx.single_source_dijkstra_path_length(
            Gu, source=src, cutoff=WALK_TIME_CUTOFF_S, weight="walk_time_s"
        )
        reach_counts.append(len(d))
    districts["walk_reach_nodes_10min_point"] = reach_counts

    t4 = perf_counter()
    print(f"  ok (dt={t4 - t3:.1f}s)")

    print("[5/6] metro_walk_time_s_point ...")
    if len(metro) > 0:
        metro_wgs = metro.to_crs(WGS84)
        metro_wgs = metro_wgs[metro_wgs.geometry.type.isin(["Point", "MultiPoint"])].copy()

        if len(metro_wgs) > 0:
            metro_nodes = nearest_nodes_compat(Gu, X=metro_wgs.geometry.x.values, Y=metro_wgs.geometry.y.values)
            metro_nodes = list(set(metro_nodes))

            dist_to_metro = nx.multi_source_dijkstra_path_length(Gu, sources=metro_nodes, weight="walk_time_s")
            districts["metro_walk_time_s_point"] = [dist_to_metro.get(n, float("nan")) for n in src_nodes]
        else:
            districts["metro_walk_time_s_point"] = float("nan")
    else:
        districts["metro_walk_time_s_point"] = float("nan")

    t5 = perf_counter()
    print(f"  ok (dt={t5 - t4:.1f}s)")

    print("[6/6] Save ...")
    districts.to_file(OUT_GPKG, layer=OUT_LAYER, driver="GPKG")
    districts.drop(columns=["geometry"], errors="ignore").to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    t6 = perf_counter()
    print("DONE")
    print("CSV :", OUT_CSV)
    print("GPKG:", OUT_GPKG)
    print(f"TOTAL dt={t6 - t0:.1f}s)")


if __name__ == "__main__":
    main()
