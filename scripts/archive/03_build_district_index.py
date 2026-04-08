# 03_build_district_index.py
# Собирает итоговый индекс привлекательности по полигонам (МО) на основе уже посчитанных метрик.
# Вход:
#   - pvz_project/district_features_walk.gpkg (layer: districts_features_walk)
# Выход:
#   - pvz_project/district_index.csv
#   - pvz_project/district_index.gpkg (layer: districts_index)

from pathlib import Path
import numpy as np
import geopandas as gpd


PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

IN_GPKG = PROJECT_DIR / "district_features_walk.gpkg"
IN_LAYER = "districts_features_walk"

OUT_CSV = PROJECT_DIR / "district_index.csv"
OUT_GPKG = PROJECT_DIR / "district_index.gpkg"
OUT_LAYER = "districts_index"


# Веса (можешь менять). Сумма не обязана быть 1, мы нормализуем автоматически.
WEIGHTS = {
    # спрос/плотность жилья (плюс)
    "res_buildings_density_km2": 0.30,

    # “пешеходная связность” вокруг точки внутри полигона (плюс)
    "walk_reach_nodes_10min_point": 0.25,

    # время пешком до метро (минус)
    "metro_walk_time_s_point": 0.20,

    # конкуренты (минус)
    "competitor_density_km2": 0.15,

    # общежития (плюс)
    "dormitory_cnt": 0.05,

    # кладбища (минус)
    "cemetery_area_share": 0.05,
}

# Какие признаки считаем "минусовыми"
NEGATIVE = {
    "metro_walk_time_s_point",
    "competitor_density_km2",
    "cemetery_area_share",
}


def pct_rank(s):
    # робастная нормализация: перцентильный ранг 0..1
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
        raise RuntimeError(
            "Не хватает колонок для индекса:\n  - " + "\n  - ".join(missing) +
            "\nПроверь, что ты запускал 01 и 02 и что файлы из правильной папки."
        )

    # 1) нормализация в 0..1
    for col in WEIGHTS.keys():
        gdf[col + "_pct"] = pct_rank(gdf[col])
        if col in NEGATIVE:
            gdf[col + "_pct"] = 1.0 - gdf[col + "_pct"]

    # 2) взвешенная сумма (игнорируем NaN: вес перераспределяется на доступные признаки)
    w_sum = np.zeros(len(gdf), dtype=float)
    w_tot = np.zeros(len(gdf), dtype=float)

    for col, w in WEIGHTS.items():
        x = gdf[col + "_pct"].to_numpy(dtype=float)
        m = np.isfinite(x)
        w_sum[m] += w * x[m]
        w_tot[m] += w

    gdf["index_score_0_1"] = np.where(w_tot > 0, w_sum / w_tot, np.nan)

    # 3) ранги
    gdf["index_rank"] = gdf["index_score_0_1"].rank(ascending=False, method="min")
    gdf = gdf.sort_values("index_score_0_1", ascending=False)

    # 4) сохранить
    gdf.drop(columns=["geometry"], errors="ignore").to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    gdf.to_file(OUT_GPKG, layer=OUT_LAYER, driver="GPKG")

    # 5) показать топ/низ в консоль
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
