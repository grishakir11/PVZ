# 17b_plot_points_two_colors.py
# Рисует две сети K=20 разными цветами + легенда:
# - baseline (охват 10 мин): первые 20 точек из pvz_selected_kmax.csv
# - min-mean (минимизация среднего времени): pvz_selected_mean_k20.csv
#
# Выход:
#   pvz_project/map_points_k20_baseline_red_mean_blue.png

from pathlib import Path
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt

PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

PVZ_RANKED_CSV = PROJECT_DIR / "pvz_selected_kmax.csv"
PVZ_MEAN_CSV = PROJECT_DIR / "pvz_selected_mean_k20.csv"

POLY_GPKG = PROJECT_DIR / "district_index_v2.gpkg"
POLY_LAYER = "districts_index_v2"

OUT_PNG = PROJECT_DIR / "map_points_k20_baseline_red_mean_blue.png"

WGS84 = "EPSG:4326"
METRIC_CRS = "EPSG:32637"
K = 20


def load_points(csv_path: Path, k: int) -> gpd.GeoDataFrame:
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    if "sel_rank" in df.columns:
        df = df.sort_values("sel_rank")
    df = df.head(k).copy()
    if not {"lat", "lon"}.issubset(df.columns):
        raise RuntimeError(f"{csv_path} должен содержать lat/lon")
    gdf = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df["lon"], df["lat"]),
        crs=WGS84,
    )
    return gdf


def main():
    polys = gpd.read_file(POLY_GPKG, layer=POLY_LAYER)
    if polys.crs is None:
        polys = polys.set_crs(METRIC_CRS, allow_override=True)
    polys = polys.to_crs(WGS84)

    base = load_points(PVZ_RANKED_CSV, K)
    mean = load_points(PVZ_MEAN_CSV, K)

    plt.figure(figsize=(10, 10))
    ax = plt.gca()

    polys.plot(ax=ax, color="#f0f0f0", edgecolor="#999999", linewidth=0.3)

    base.plot(ax=ax, markersize=28, marker="o", label="baseline (охват 10 мин)")
    mean.plot(ax=ax, markersize=28, marker="^", label="минимизация среднего времени")

    ax.set_title("Две сети K=20 (разные цвета)")
    ax.set_axis_off()
    ax.legend(loc="lower left", frameon=True)

    plt.tight_layout()
    plt.savefig(OUT_PNG, dpi=220)
    print("DONE:", OUT_PNG)


if __name__ == "__main__":
    main()