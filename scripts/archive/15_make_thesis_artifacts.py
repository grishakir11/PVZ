# 15_make_thesis_artifacts.py
# Собирает артефакты для диплома (без метро):
# 1) Перерисовывает графики:
#    - K -> share_10min
#    - K -> mean/p50/p90 времени "от дома до ПВЗ"
# 2) Делает таблицы:
#    - сводка по K (share и времена)
#    - сводка экономических сценариев по переходам (20->30, 30->40, ...)
#    - топ районов по улучшению 20->30 (Δ доли 10 мин и Δ среднего времени)
# 3) Рисует статичные PNG-карты (без интернета):
#    - Δ доля <=10 мин (K0->K1)
#    - Δ среднее время (K0->K1) (отрицательное = лучше)
#
# Вход (ожидаются в pvz_project):
#   saturation_curve_share10.csv
#   saturation_curve_time_from_home.csv
#   econ_k_metrics.csv
#   econ_transitions.csv
#   econ_scenarios.csv
#   delta_k20_k30_by_district.csv
#   district_index_v2.gpkg (layer: districts_index_v2)  <-- только геометрия + district_name
#
# Выход:
#   thesis_artifacts/
#     fig_share10_curve.png
#     fig_time_curve.png
#     fig_delta_share10_k20_k30.png
#     fig_delta_mean_time_k20_k30.png
#     table_k_summary.csv
#     table_econ_scenarios.csv
#     top_districts_by_delta_share10.csv
#     top_districts_by_delta_mean_time.csv
#     summary.txt

from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt


# ====== НАСТРОЙКИ ======
PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")
OUT_DIR = PROJECT_DIR / "thesis_artifacts"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Сценарий для карт/топов
K0 = 20
K1 = 30

# Пути
P_SHARE = PROJECT_DIR / "saturation_curve_share10.csv"
P_TIME  = PROJECT_DIR / "saturation_curve_time_from_home.csv"

P_ECON_K = PROJECT_DIR / "econ_k_metrics.csv"
P_ECON_TR = PROJECT_DIR / "econ_transitions.csv"
P_ECON_SC = PROJECT_DIR / "econ_scenarios.csv"

P_DELTA = PROJECT_DIR / "delta_k20_k30_by_district.csv"

POLY_GPKG = PROJECT_DIR / "district_index_v2.gpkg"
POLY_LAYER = "districts_index_v2"
# =======================


def _req_file(p: Path):
    if not p.exists():
        raise FileNotFoundError(f"Не найден файл: {p}")


def _read_csv(p: Path) -> pd.DataFrame:
    return pd.read_csv(p, encoding="utf-8-sig")


def _fmt(x, nd=3):
    try:
        if pd.isna(x):
            return "NA"
        return f"{float(x):.{nd}f}"
    except Exception:
        return str(x)


def plot_share_curve(df: pd.DataFrame, out_png: Path):
    need = {"K", "share_10min"}
    if not need.issubset(df.columns):
        raise RuntimeError(f"{P_SHARE}: нужны колонки {need}, есть {set(df.columns)}")

    d = df.sort_values("K").copy()
    plt.figure()
    plt.plot(d["K"].values, d["share_10min"].values, marker="o")
    plt.xlabel("Число пунктов выдачи (K)")
    plt.ylabel("Доля спроса в пределах 10 минут")
    plt.title("Кривая насыщения: K → доля спроса ≤ 10 мин (пешком от дома)")
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(out_png, dpi=180)


def plot_time_curve(df: pd.DataFrame, out_png: Path):
    need = {"K", "mean_time_min", "p50_time_min", "p90_time_min"}
    if not need.issubset(df.columns):
        raise RuntimeError(f"{P_TIME}: нужны колонки {need}, есть {set(df.columns)}")

    d = df.sort_values("K").copy()
    plt.figure()
    plt.plot(d["K"].values, d["mean_time_min"].values, marker="o", label="среднее (мин)")
    plt.plot(d["K"].values, d["p50_time_min"].values, marker="o", label="медиана p50 (мин)")
    plt.plot(d["K"].values, d["p90_time_min"].values, marker="o", label="p90 (мин)")
    plt.xlabel("Число пунктов выдачи (K)")
    plt.ylabel("Время пешком до ближайшего пункта (мин)")
    plt.title("Кривая насыщения: K → время до ближайшего пункта (от дома)")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png, dpi=180)


def make_k_summary(df_share: pd.DataFrame, df_time: pd.DataFrame, out_csv: Path) -> pd.DataFrame:
    # объединяем по K
    a = df_share[["K", "share_10min"]].copy()
    b = df_time[["K", "mean_time_min", "p50_time_min", "p90_time_min"]].copy()
    m = a.merge(b, on="K", how="outer").sort_values("K")
    m.to_csv(out_csv, index=False, encoding="utf-8-sig")
    return m


def save_econ_scenarios_table(df_sc: pd.DataFrame, out_csv: Path):
    # сохраняем как есть + отсортируем
    cols = [
        "scenario", "K_from", "K_to", "delta_K",
        "delta_D",
        "delta_orders_month",
        "delta_profit_month_rub",
        "payback_months",
        "margin_per_order_rub",
        "fixed_cost_per_pvz_month_rub",
        "open_cost_per_pvz_rub",
    ]
    have = [c for c in cols if c in df_sc.columns]
    d = df_sc[have].copy()
    if "scenario" in d.columns and "K_from" in d.columns and "K_to" in d.columns:
        d = d.sort_values(["scenario", "K_from", "K_to"])
    d.to_csv(out_csv, index=False, encoding="utf-8-sig")


def top_districts(df_delta: pd.DataFrame, out1: Path, out2: Path, topn=30):
    if "district_name" not in df_delta.columns:
        raise RuntimeError("В delta_k20_k30_by_district.csv нет district_name")

    # TOP по приросту доли 10 мин
    c1 = "delta_share_10min"
    if c1 in df_delta.columns:
        t1 = df_delta[["district_name", c1]].copy()
        t1 = t1.sort_values(c1, ascending=False).head(topn)
        t1.to_csv(out1, index=False, encoding="utf-8-sig")

    # TOP по улучшению среднего времени (самое отрицательное = лучше)
    c2 = "delta_mean_time_min"
    if c2 in df_delta.columns:
        t2 = df_delta[["district_name", c2]].copy()
        t2 = t2.sort_values(c2, ascending=True).head(topn)
        t2.to_csv(out2, index=False, encoding="utf-8-sig")


def plot_delta_maps(polys: gpd.GeoDataFrame, df_delta: pd.DataFrame, out_share_png: Path, out_mean_png: Path):
    if "district_name" not in polys.columns:
        raise RuntimeError("В полигонах нет district_name")
    if "district_name" not in df_delta.columns:
        raise RuntimeError("В delta CSV нет district_name")

    g = polys.merge(df_delta, on="district_name", how="left")

    # Δ доли <=10 минут
    if "delta_share_10min" in g.columns:
        plt.figure(figsize=(10, 10))
        ax = plt.gca()
        g.plot(column="delta_share_10min", ax=ax, legend=True, missing_kwds={"color": "#cccccc"})
        ax.set_title(f"Δ доля спроса в 10 мин (K={K0}→{K1})")
        ax.set_axis_off()
        plt.tight_layout()
        plt.savefig(out_share_png, dpi=220)

    # Δ среднего времени (отрицательное=лучше)
    if "delta_mean_time_min" in g.columns:
        plt.figure(figsize=(10, 10))
        ax = plt.gca()
        g.plot(column="delta_mean_time_min", ax=ax, legend=True, missing_kwds={"color": "#cccccc"})
        ax.set_title(f"Δ среднее время, мин (K={K0}→{K1}), отрицательное = улучшение")
        ax.set_axis_off()
        plt.tight_layout()
        plt.savefig(out_mean_png, dpi=220)


def write_summary_txt(k_summary: pd.DataFrame, out_txt: Path):
    lines = []
    lines.append("SUMMARY (без метро)")
    lines.append("")

    # ключевые K
    for k in [K0, K1, 40, 60]:
        row = k_summary[k_summary["K"] == k]
        if len(row) == 0:
            continue
        r = row.iloc[0]
        lines.append(
            f"K={int(k)}: share_10min={_fmt(r.get('share_10min', np.nan), 4)}, "
            f"mean={_fmt(r.get('mean_time_min', np.nan), 1)} min, "
            f"p50={_fmt(r.get('p50_time_min', np.nan), 1)} min, "
            f"p90={_fmt(r.get('p90_time_min', np.nan), 1)} min"
        )

    # дельты 20->30
    row0 = k_summary[k_summary["K"] == K0]
    row1 = k_summary[k_summary["K"] == K1]
    if len(row0) and len(row1):
        r0 = row0.iloc[0]
        r1 = row1.iloc[0]
        ds = float(r1["share_10min"]) - float(r0["share_10min"])
        dmean = float(r1["mean_time_min"]) - float(r0["mean_time_min"])
        dp50 = float(r1["p50_time_min"]) - float(r0["p50_time_min"])
        lines.append("")
        lines.append(f"Δ(K={K0}→{K1}): Δshare_10min={ds:+.4f}, Δmean_time={dmean:+.1f} min, Δp50={dp50:+.1f} min")

    out_txt.write_text("\n".join(lines), encoding="utf-8")


def main():
    # входы
    _req_file(P_SHARE)
    _req_file(P_TIME)
    _req_file(P_ECON_K)
    _req_file(P_ECON_TR)
    _req_file(P_ECON_SC)
    _req_file(P_DELTA)
    _req_file(POLY_GPKG)

    df_share = _read_csv(P_SHARE)
    df_time = _read_csv(P_TIME)

    df_sc = _read_csv(P_ECON_SC)
    df_delta = _read_csv(P_DELTA)

    polys = gpd.read_file(POLY_GPKG, layer=POLY_LAYER)

    # графики
    plot_share_curve(df_share, OUT_DIR / "fig_share10_curve.png")
    plot_time_curve(df_time, OUT_DIR / "fig_time_curve.png")

    # таблица K
    k_summary = make_k_summary(df_share, df_time, OUT_DIR / "table_k_summary.csv")

    # экономика
    save_econ_scenarios_table(df_sc, OUT_DIR / "table_econ_scenarios.csv")

    # топ районов
    top_districts(
        df_delta,
        OUT_DIR / "top_districts_by_delta_share10.csv",
        OUT_DIR / "top_districts_by_delta_mean_time.csv",
        topn=30,
    )

    # карты (PNG без интернета)
    plot_delta_maps(
        polys,
        df_delta,
        OUT_DIR / f"fig_delta_share10_k{K0}_k{K1}.png",
        OUT_DIR / f"fig_delta_mean_time_k{K0}_k{K1}.png",
    )

    # summary
    write_summary_txt(k_summary, OUT_DIR / "summary.txt")

    print("DONE")
    print("OUT:", OUT_DIR)


if __name__ == "__main__":
    main()