# 14b_delta_png_no_internet.py
# Рисует статичные PNG по улучшению K=20->30 без подложки и без интернета.

from pathlib import Path
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt

PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

POLY_GPKG = PROJECT_DIR / "district_index_v2.gpkg"
POLY_LAYER = "districts_index_v2"

DELTA_CSV = PROJECT_DIR / "delta_k20_k30_by_district.csv"

OUT1 = PROJECT_DIR / "delta_share_10min_k20_k30.png"
OUT2 = PROJECT_DIR / "delta_mean_time_min_k20_k30.png"

WGS84 = "EPSG:4326"

def main():
    polys = gpd.read_file(POLY_GPKG, layer=POLY_LAYER)
    df = pd.read_csv(DELTA_CSV, encoding="utf-8-sig")

    if "district_name" not in polys.columns:
        raise RuntimeError("В полигонах нет district_name.")
    if "district_name" not in df.columns:
        raise RuntimeError("В delta CSV нет district_name.")

    g = polys.merge(df, on="district_name", how="left")
    if g.crs is not None:
        g = g.to_crs(WGS84)

    # 1) Δ доли <=10 минут
    plt.figure(figsize=(10, 10))
    ax = plt.gca()
    g.plot(column="delta_share_10min", ax=ax, legend=True, missing_kwds={"color": "#cccccc"})
    ax.set_title("Δ доля спроса в 10 мин (K=20→30)")
    ax.set_axis_off()
    plt.tight_layout()
    plt.savefig(OUT1, dpi=200)

    # 2) Δ среднего времени (отрицательное = лучше)
    plt.figure(figsize=(10, 10))
    ax = plt.gca()
    g.plot(column="delta_mean_time_min", ax=ax, legend=True, missing_kwds={"color": "#cccccc"})
    ax.set_title("Δ среднее время, мин (K=20→30), отрицательное = улучшение")
    ax.set_axis_off()
    plt.tight_layout()
    plt.savefig(OUT2, dpi=200)

    print("DONE")
    print(OUT1)
    print(OUT2)

if __name__ == "__main__":
    main()