# 10_priority_districts_report.py
# Делает таблицу "где болит": высокий спрос + низкое удобство (share_10min)
# и сохраняет приоритеты по районам.
#
# Вход:
#   - pvz_project/district_resident_metrics.csv (из 08_resident_demand_convenience_by_district.py)
# Выход:
#   - pvz_project/district_priority.csv
#   - pvz_project/district_priority.txt

from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_DIR = Path(r"C:\Users\sgs-w\Downloads\pvz_project")

IN_CSV = PROJECT_DIR / "district_resident_metrics.csv"
OUT_CSV = PROJECT_DIR / "district_priority.csv"
OUT_TXT = PROJECT_DIR / "district_priority.txt"

def main():
    df = pd.read_csv(IN_CSV, encoding="utf-8-sig")

    need = ["district_name", "demand_total", "share_10min", "p50_time_min", "p90_time_min"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise RuntimeError("В district_resident_metrics.csv нет колонок: " + ", ".join(missing))

    df = df.copy()
    df["demand_total"] = pd.to_numeric(df["demand_total"], errors="coerce")
    df["share_10min"] = pd.to_numeric(df["share_10min"], errors="coerce")
    df["p50_time_min"] = pd.to_numeric(df["p50_time_min"], errors="coerce")
    df["p90_time_min"] = pd.to_numeric(df["p90_time_min"], errors="coerce")

    # Непокрытый спрос (весом)
    df["unserved_demand_10min"] = df["demand_total"] * (1.0 - df["share_10min"])

    # Приоритет: непокрытый спрос, усиленный штрафом за плохую медиану/хвост
    # (это уже "как жителям плохо", а не только "сколько не покрыто")
    df["time_penalty"] = 1.0 + np.clip((df["p50_time_min"] - 10.0) / 10.0, 0.0, 2.0) + 0.5 * np.clip((df["p90_time_min"] - 15.0) / 15.0, 0.0, 2.0)
    df["priority_score"] = df["unserved_demand_10min"] * df["time_penalty"]

    # Полезные проценты
    df["share_10min_pct"] = df["share_10min"] * 100.0

    out = df[[
        "district_name",
        "demand_total",
        "share_10min",
        "share_10min_pct",
        "p50_time_min",
        "p90_time_min",
        "unserved_demand_10min",
        "priority_score",
    ]].sort_values("priority_score", ascending=False)

    out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    # Короткий текстовый отчёт
    total_demand = float(np.nansum(df["demand_total"].values))
    total_unserved = float(np.nansum(df["unserved_demand_10min"].values))
    city_share10 = 1.0 - (total_unserved / total_demand if total_demand > 0 else np.nan)

    top10 = out.head(10)

    lines = []
    lines.append("CITY SUMMARY")
    lines.append(f"total_demand_total = {total_demand:,.0f}")
    lines.append(f"unserved_demand_10min = {total_unserved:,.0f}")
    lines.append(f"city_share_10min (approx from district totals) = {city_share10:.3f}")
    lines.append("")
    lines.append("TOP 10 PRIORITY DISTRICTS (high demand + low convenience)")
    for _, r in top10.iterrows():
        lines.append(
            f"{r['district_name']}: "
            f"priority={r['priority_score']:.2e}, "
            f"unserved={r['unserved_demand_10min']:.2e}, "
            f"share10={r['share_10min']:.3f}, "
            f"p50={r['p50_time_min']:.1f}m, "
            f"p90={r['p90_time_min']:.1f}m"
        )

    OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
    print("DONE")
    print("CSV:", OUT_CSV)
    print("TXT:", OUT_TXT)

if __name__ == "__main__":
    main()
