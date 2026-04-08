# 22_make_k20_conclusion_tables.py
# Делает итоговые таблицы и графики по 4 сетям K=20 для главы "результаты" и "заключение".
#
# Вход:
#   - pvz_project/compare_k20_four_objectives.csv
#   - pvz_project/compare_k20_four_by_district.csv
#
# Выход:
#   - pvz_project/k20_final_summary_city.csv
#   - pvz_project/k20_final_deltas_vs_base.csv
#   - pvz_project/k20_top_keep_mean_vs_base.csv
#   - pvz_project/k20_top_keep_share10_vs_base.csv
#   - pvz_project/k20_method_wins_by_district.csv
#   - pvz_project/k20_top_keep_mean_vs_eff.csv
#   - pvz_project/k20_top_keep_share10_vs_eff.csv
#   - pvz_project/fig_k20_top_keep_mean_vs_base.png
#   - pvz_project/fig_k20_top_keep_share10_vs_base.png

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

CITY_CSV = PROJECT_DIR / "compare_k20_four_objectives.csv"
DIST_CSV = PROJECT_DIR / "compare_k20_four_by_district.csv"

OUT_CITY = PROJECT_DIR / "k20_final_summary_city.csv"
OUT_DELTAS = PROJECT_DIR / "k20_final_deltas_vs_base.csv"
OUT_TOP_MEAN_BASE = PROJECT_DIR / "k20_top_keep_mean_vs_base.csv"
OUT_TOP_SHARE_BASE = PROJECT_DIR / "k20_top_keep_share10_vs_base.csv"
OUT_WINS = PROJECT_DIR / "k20_method_wins_by_district.csv"
OUT_TOP_MEAN_EFF = PROJECT_DIR / "k20_top_keep_mean_vs_eff.csv"
OUT_TOP_SHARE_EFF = PROJECT_DIR / "k20_top_keep_share10_vs_eff.csv"

OUT_FIG_MEAN = PROJECT_DIR / "fig_k20_top_keep_mean_vs_base.png"
OUT_FIG_SHARE = PROJECT_DIR / "fig_k20_top_keep_share10_vs_base.png"


def main():
    city = pd.read_csv(CITY_CSV, encoding="utf-8-sig")
    dist = pd.read_csv(DIST_CSV, encoding="utf-8-sig")

    # 1) Городская итоговая таблица как есть
    city.to_csv(OUT_CITY, index=False, encoding="utf-8-sig")

    # 2) Дельты относительно baseline по городу
    base = city.loc[city["method"] == "baseline_coverage10"].iloc[0]

    rows = []
    for _, r in city.iterrows():
        if r["method"] == "baseline_coverage10":
            continue
        rows.append({
            "method": r["method"],
            "delta_share_10min_vs_base": r["share_10min"] - base["share_10min"],
            "delta_mean_time_min_vs_base": r["mean_time_min"] - base["mean_time_min"],
            "delta_p50_time_min_vs_base": r["p50_time_min"] - base["p50_time_min"],
            "delta_p90_time_min_vs_base": r["p90_time_min"] - base["p90_time_min"],
            "delta_D_effective_share_vs_base": r["D_effective_share"] - base["D_effective_share"],
        })
    deltas = pd.DataFrame(rows)
    deltas.to_csv(OUT_DELTAS, index=False, encoding="utf-8-sig")

    # 3) ТОП районов: keep_zelenograd против baseline
    need_cols = {
        "district_name",
        "delta_keep_minus_base",
        "delta_share10_keep_minus_base",
        "mean_time_min_keep",
        "mean_time_min_base",
        "share_10min_keep",
        "share_10min_base",
    }
    missing = need_cols - set(dist.columns)
    if missing:
        raise RuntimeError(f"В compare_k20_four_by_district.csv не хватает колонок: {missing}")

    top_mean_base = dist[
        [
            "district_name",
            "mean_time_min_base",
            "mean_time_min_keep",
            "delta_keep_minus_base",
        ]
    ].sort_values("delta_keep_minus_base", ascending=True).head(20).copy()
    top_mean_base.to_csv(OUT_TOP_MEAN_BASE, index=False, encoding="utf-8-sig")

    top_share_base = dist[
        [
            "district_name",
            "share_10min_base",
            "share_10min_keep",
            "delta_share10_keep_minus_base",
        ]
    ].sort_values("delta_share10_keep_minus_base", ascending=False).head(20).copy()
    top_share_base.to_csv(OUT_TOP_SHARE_BASE, index=False, encoding="utf-8-sig")

    # 4) keep_zelenograd против чистого effective
    if not {
        "mean_time_min_eff",
        "mean_time_min_keep",
        "share_10min_eff",
        "share_10min_keep",
    }.issubset(dist.columns):
        raise RuntimeError("Нет колонок *_eff / *_keep в районной таблице.")

    tmp = dist.copy()
    tmp["delta_keep_vs_eff_mean"] = tmp["mean_time_min_keep"] - tmp["mean_time_min_eff"]
    tmp["delta_keep_vs_eff_share10"] = tmp["share_10min_keep"] - tmp["share_10min_eff"]

    top_mean_eff = tmp[
        ["district_name", "mean_time_min_eff", "mean_time_min_keep", "delta_keep_vs_eff_mean"]
    ].sort_values("delta_keep_vs_eff_mean", ascending=True).head(20).copy()
    top_mean_eff.to_csv(OUT_TOP_MEAN_EFF, index=False, encoding="utf-8-sig")

    top_share_eff = tmp[
        ["district_name", "share_10min_eff", "share_10min_keep", "delta_keep_vs_eff_share10"]
    ].sort_values("delta_keep_vs_eff_share10", ascending=False).head(20).copy()
    top_share_eff.to_csv(OUT_TOP_SHARE_EFF, index=False, encoding="utf-8-sig")

    # 5) Кто "побеждает" по районам
    methods = {
        "base": "baseline_coverage10",
        "mean": "min_mean_time",
        "eff": "max_effective_demand",
        "keep": "effective_keep_zelenograd",
    }

    win_rows = []
    for _, r in dist.iterrows():
        mean_vals = {
            "baseline_coverage10": r["mean_time_min_base"],
            "min_mean_time": r["mean_time_min_mean"],
            "max_effective_demand": r["mean_time_min_eff"],
            "effective_keep_zelenograd": r["mean_time_min_keep"],
        }
        share_vals = {
            "baseline_coverage10": r["share_10min_base"],
            "min_mean_time": r["share_10min_mean"],
            "max_effective_demand": r["share_10min_eff"],
            "effective_keep_zelenograd": r["share_10min_keep"],
        }

        best_mean_method = min(mean_vals, key=mean_vals.get)
        best_share_method = max(share_vals, key=share_vals.get)

        win_rows.append({
            "district_name": r["district_name"],
            "best_by_mean_time": best_mean_method,
            "best_by_share10": best_share_method,
        })

    wins = pd.DataFrame(win_rows)
    wins.to_csv(OUT_WINS, index=False, encoding="utf-8-sig")

    # 6) Простые графики для главы
    plot_mean = top_mean_base.sort_values("delta_keep_minus_base", ascending=False).copy()
    plt.figure(figsize=(10, 8))
    plt.barh(plot_mean["district_name"], plot_mean["delta_keep_minus_base"])
    plt.xlabel("Δ среднего времени, мин (keep_zelenograd − baseline)")
    plt.ylabel("Район")
    plt.title("Топ-20 районов по улучшению среднего времени\n(отрицательное = лучше)")
    plt.tight_layout()
    plt.savefig(OUT_FIG_MEAN, dpi=220)
    plt.close()

    plot_share = top_share_base.sort_values("delta_share10_keep_minus_base", ascending=True).copy()
    plt.figure(figsize=(10, 8))
    plt.barh(plot_share["district_name"], plot_share["delta_share10_keep_minus_base"])
    plt.xlabel("Δ доли спроса ≤10 мин (keep_zelenograd − baseline)")
    plt.ylabel("Район")
    plt.title("Топ-20 районов по росту доли спроса ≤10 мин")
    plt.tight_layout()
    plt.savefig(OUT_FIG_SHARE, dpi=220)
    plt.close()

    print("DONE")
    print("CITY:", OUT_CITY)
    print("DELTAS:", OUT_DELTAS)
    print("TOP mean vs base:", OUT_TOP_MEAN_BASE)
    print("TOP share10 vs base:", OUT_TOP_SHARE_BASE)
    print("TOP mean vs eff:", OUT_TOP_MEAN_EFF)
    print("TOP share10 vs eff:", OUT_TOP_SHARE_EFF)
    print("WINS:", OUT_WINS)
    print("FIG:", OUT_FIG_MEAN)
    print("FIG:", OUT_FIG_SHARE)


if __name__ == "__main__":
    main()
