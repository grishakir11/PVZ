# 03_build_district_index_v2.py
# Индекс на multipoint-метриках (устойчивый к выбору точки внутри полигона).

from pathlib import Path
import numpy as np
import geopandas as gpd

PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

IN_GPKG = PROJECT_DIR / "district_features_walk_mp.gpkg"
IN_LAYER = "districts_features_walk_mp"

OUT_CSV = PROJECT_DIR / "district_index_v2.csv"
OUT_GPKG = PROJECT_DIR / "district_index_v2.gpkg"
OUT_LAYER = "districts_index_v2"

WEIGHTS = {
    "res_buildings_density_km2": 0.30,
    "walk_reach_nodes_10min_p50": 0.25,   # вместо *_point
    "metro_walk_time_s_p10": 0.20,        # вместо *_point
    "competitor_density_km2": 0.15,
    "dormitory_cnt": 0.05,
    "cemetery_area_share": 0.05,
}

NEGATIVE = {
    "metro_walk_time_s_p10",
    "competitor_density_km2",
    "cemetery_area_share",
}

def pct_rank(s):
    s = s.astype(float)
    m = np.isfinite(s)
    out = np.full(len(s), np.nan, dtype=float)
    if m.sum() == 0:
        return out
    out[m] = s[m].rank(pct=True).to_numpy()
    return out

def main():
    gdf = gpd.read_file(IN_GPKG, layer=IN_LAYER)

    missing = [c for c in WEIGHTS.keys() if c not in gdf.columns]
    if missing:
        raise RuntimeError("Не хватает колонок:\n  - " + "\n  - ".join(missing))

    for col in WEIGHTS.keys():
        gdf[col + "_pct"] = pct_rank(gdf[col])
        if col in NEGATIVE:
            gdf[col + "_pct"] = 1.0 - gdf[col + "_pct"]

    w_sum = np.zeros(len(gdf), dtype=float)
    w_tot = np.zeros(len(gdf), dtype=float)

    for col, w in WEIGHTS.items():
        x = gdf[col + "_pct"].to_numpy(dtype=float)
        m = np.isfinite(x)
        w_sum[m] += w * x[m]
        w_tot[m] += w

    gdf["index_score_0_1"] = np.where(w_tot > 0, w_sum / w_tot, np.nan)
    gdf["index_rank"] = gdf["index_score_0_1"].rank(ascending=False, method="min")
    gdf = gdf.sort_values("index_score_0_1", ascending=False)

    gdf.drop(columns=["geometry"], errors="ignore").to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    gdf.to_file(OUT_GPKG, layer=OUT_LAYER, driver="GPKG")

    show_cols = ["district_name", "index_score_0_1", "index_rank"]
    print("\nTOP 15:")
    print(gdf[show_cols].head(15).to_string(index=False))
    print("\nBOTTOM 15:")
    print(gdf[show_cols].tail(15).to_string(index=False))

    print("\nDONE")
    print("CSV :", OUT_CSV)
    print("GPKG:", OUT_GPKG)

if __name__ == "__main__":
    main()
