# 04_diagnose_index.py
# Показывает вклад каждого признака в итоговый score и сохраняет breakdown в CSV.

from pathlib import Path
import pandas as pd
import geopandas as gpd

PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

IN_GPKG = PROJECT_DIR / "district_index.gpkg"
IN_LAYER = "districts_index"

OUT_CSV = PROJECT_DIR / "district_index_breakdown.csv"

WEIGHTS = {
    "res_buildings_density_km2": 0.30,
    "walk_reach_nodes_10min_point": 0.25,
    "metro_walk_time_s_point": 0.20,
    "competitor_density_km2": 0.15,
    "dormitory_cnt": 0.05,
    "cemetery_area_share": 0.05,
}

# в district_index.gpkg после 03 есть колонки *_pct
def main():
    gdf = gpd.read_file(IN_GPKG, layer=IN_LAYER)

    need_pct = [c + "_pct" for c in WEIGHTS.keys()]
    missing = [c for c in need_pct if c not in gdf.columns]
    if missing:
        raise RuntimeError("В индексе нет *_pct колонок. Запусти заново 03_build_district_index.py.")

    # вклад = weight * pct, потом нормализуем на сумму весов без NaN
    contrib = {}
    wtot = 0.0
    for col, w in WEIGHTS.items():
        contrib[col + "_contrib"] = gdf[col + "_pct"].astype(float) * w
        wtot += w

    df = pd.DataFrame(contrib)
    df.insert(0, "district_name", gdf["district_name"].astype(str))
    df["index_score_0_1"] = gdf["index_score_0_1"].astype(float)
    df["index_rank"] = gdf["index_rank"].astype(float)

    # топ-3 вкладов по району
    cols = [c for c in df.columns if c.endswith("_contrib")]
    top3 = []
    for i in range(len(df)):
        row = df.loc[i, cols].sort_values(ascending=False)
        top3.append(", ".join([f"{k.replace('_contrib','')}={row[k]:.3f}" for k in row.index[:3]]))
    df["top3_contrib"] = top3

    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    watch = ["Кунцево", "Щербинка", "Косино-Ухтомский", "Сокол", "Арбат"]
    print("\nWATCH LIST:")
    print(df[df["district_name"].isin(watch)][
        ["district_name", "index_score_0_1", "index_rank", "top3_contrib"]
    ].to_string(index=False))

    print("\nDONE:", OUT_CSV)

if __name__ == "__main__":
    main()
