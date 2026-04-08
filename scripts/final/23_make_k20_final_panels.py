# 23_make_k20_final_panels.py
# Финальные диаграммы для главы результатов по K=20.
#
# Вход:
#   - pvz_project/compare_k20_four_objectives.csv
#   - pvz_project/k20_top_keep_mean_vs_base.csv
#   - pvz_project/k20_top_keep_share10_vs_base.csv
#   - pvz_project/k20_top_keep_mean_vs_eff.csv
#   - pvz_project/k20_top_keep_share10_vs_eff.csv
#
# Выход:
#   - pvz_project/fig_city_share10_methods.png
#   - pvz_project/fig_city_mean_methods.png
#   - pvz_project/fig_city_p50_methods.png
#   - pvz_project/fig_city_p90_methods.png
#   - pvz_project/fig_city_deff_methods.png
#   - pvz_project/fig_top_keep_mean_vs_base.png
#   - pvz_project/fig_top_keep_share10_vs_base.png
#   - pvz_project/fig_top_keep_mean_vs_eff.png
#   - pvz_project/fig_top_keep_share10_vs_eff.png

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

CITY_CSV = PROJECT_DIR / "compare_k20_four_objectives.csv"
TOP_MEAN_BASE = PROJECT_DIR / "k20_top_keep_mean_vs_base.csv"
TOP_SHARE_BASE = PROJECT_DIR / "k20_top_keep_share10_vs_base.csv"
TOP_MEAN_EFF = PROJECT_DIR / "k20_top_keep_mean_vs_eff.csv"
TOP_SHARE_EFF = PROJECT_DIR / "k20_top_keep_share10_vs_eff.csv"

OUT_CITY_SHARE10 = PROJECT_DIR / "fig_city_share10_methods.png"
OUT_CITY_MEAN = PROJECT_DIR / "fig_city_mean_methods.png"
OUT_CITY_P50 = PROJECT_DIR / "fig_city_p50_methods.png"
OUT_CITY_P90 = PROJECT_DIR / "fig_city_p90_methods.png"
OUT_CITY_DEFF = PROJECT_DIR / "fig_city_deff_methods.png"

OUT_TOP_MEAN_BASE = PROJECT_DIR / "fig_top_keep_mean_vs_base.png"
OUT_TOP_SHARE_BASE = PROJECT_DIR / "fig_top_keep_share10_vs_base.png"
OUT_TOP_MEAN_EFF = PROJECT_DIR / "fig_top_keep_mean_vs_eff.png"
OUT_TOP_SHARE_EFF = PROJECT_DIR / "fig_top_keep_share10_vs_eff.png"


METHOD_LABELS = {
    "baseline_coverage10": "baseline\nохват 10 мин",
    "min_mean_time": "минимизация\nсреднего",
    "max_effective_demand": "эффективный\nспрос",
    "effective_keep_zelenograd": "effective +\nЗеленоград",
}


def _prep_city(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["label"] = df["method"].map(METHOD_LABELS).fillna(df["method"])
    return df


def bar_city(df: pd.DataFrame, ycol: str, ylabel: str, title: str, out_png: Path):
    d = _prep_city(df)
    plt.figure(figsize=(8, 5))
    plt.bar(d["label"], d[ycol])
    plt.ylabel(ylabel)
    plt.title(title)
    plt.tight_layout()
    plt.savefig(out_png, dpi=220)
    plt.close()


def barh_top(df: pd.DataFrame, name_col: str, val_col: str, xlabel: str, title: str, out_png: Path, ascending=True):
    d = df.copy().sort_values(val_col, ascending=ascending).head(15)
    plt.figure(figsize=(9, 7))
    plt.barh(d[name_col], d[val_col])
    plt.xlabel(xlabel)
    plt.title(title)
    plt.tight_layout()
    plt.savefig(out_png, dpi=220)
    plt.close()


def main():
    city = pd.read_csv(CITY_CSV, encoding="utf-8-sig")
    top_mean_base = pd.read_csv(TOP_MEAN_BASE, encoding="utf-8-sig")
    top_share_base = pd.read_csv(TOP_SHARE_BASE, encoding="utf-8-sig")
    top_mean_eff = pd.read_csv(TOP_MEAN_EFF, encoding="utf-8-sig")
    top_share_eff = pd.read_csv(TOP_SHARE_EFF, encoding="utf-8-sig")

    # Городские сравнения
    bar_city(
        city, "share_10min",
        "Доля спроса ≤ 10 минут",
        "K=20: сравнение методов по доле спроса ≤10 минут",
        OUT_CITY_SHARE10
    )
    bar_city(
        city, "mean_time_min",
        "Среднее время, мин",
        "K=20: сравнение методов по среднему времени",
        OUT_CITY_MEAN
    )
    bar_city(
        city, "p50_time_min",
        "Медиана, мин",
        "K=20: сравнение методов по медианному времени",
        OUT_CITY_P50
    )
    bar_city(
        city, "p90_time_min",
        "P90, мин",
        "K=20: сравнение методов по верхнему процентилю времени",
        OUT_CITY_P90
    )
    bar_city(
        city, "D_effective_share",
        "Доля эффективного спроса",
        "K=20: сравнение методов по эффективному спросу",
        OUT_CITY_DEFF
    )

    # keep vs baseline
    barh_top(
        top_mean_base,
        "district_name",
        "delta_keep_minus_base",
        "Δ среднего времени, мин (keep − baseline)",
        "Топ районов: effect_keep_zelenograd против baseline\n(отрицательное = лучше)",
        OUT_TOP_MEAN_BASE,
        ascending=True,
    )
    barh_top(
        top_share_base,
        "district_name",
        "delta_share10_keep_minus_base",
        "Δ доли спроса ≤10 мин (keep − baseline)",
        "Топ районов: effect_keep_zelenograd против baseline\n(рост доли ≤10 мин)",
        OUT_TOP_SHARE_BASE,
        ascending=False,
    )

    # keep vs effective
    barh_top(
        top_mean_eff,
        "district_name",
        "delta_keep_vs_eff_mean",
        "Δ среднего времени, мин (keep − effective)",
        "Топ районов: effect_keep_zelenograd против чистого effective\n(отрицательное = keep лучше)",
        OUT_TOP_MEAN_EFF,
        ascending=True,
    )
    barh_top(
        top_share_eff,
        "district_name",
        "delta_keep_vs_eff_share10",
        "Δ доли спроса ≤10 мин (keep − effective)",
        "Топ районов: effect_keep_zelenograd против чистого effective\n(положительное = keep лучше)",
        OUT_TOP_SHARE_EFF,
        ascending=False,
    )

    print("DONE")
    print(OUT_CITY_SHARE10)
    print(OUT_CITY_MEAN)
    print(OUT_CITY_P50)
    print(OUT_CITY_P90)
    print(OUT_CITY_DEFF)
    print(OUT_TOP_MEAN_BASE)
    print(OUT_TOP_SHARE_BASE)
    print(OUT_TOP_MEAN_EFF)
    print(OUT_TOP_SHARE_EFF)


if __name__ == "__main__":
    main()
