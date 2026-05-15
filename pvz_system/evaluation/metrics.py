import numpy as np
import pandas as pd


def weighted_mean(values, weights) -> float:
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)

    mask = np.isfinite(values) & np.isfinite(weights)
    values = values[mask]
    weights = weights[mask]

    if len(values) == 0 or weights.sum() == 0:
        return float("nan")

    return float(np.average(values, weights=weights))


def weighted_share_under_threshold(times, weights, threshold: float) -> float:
    times = np.asarray(times, dtype=float)
    weights = np.asarray(weights, dtype=float)

    mask = np.isfinite(times) & np.isfinite(weights)
    times = times[mask]
    weights = weights[mask]

    if len(times) == 0 or weights.sum() == 0:
        return float("nan")

    return float(weights[times <= threshold].sum() / weights.sum())


def effective_demand(times, weights, tau: float = 10.0) -> float:
    '''
    Простая функция полезности: exp(-t / tau).
    Чем меньше время доступа, тем выше вклад точки спроса.
    '''
    times = np.asarray(times, dtype=float)
    weights = np.asarray(weights, dtype=float)

    mask = np.isfinite(times) & np.isfinite(weights)
    times = times[mask]
    weights = weights[mask]

    if len(times) == 0 or weights.sum() == 0:
        return float("nan")

    utility = np.exp(-times / tau)
    return float((weights * utility).sum() / weights.sum())


def summarize_result_table(df: pd.DataFrame) -> pd.DataFrame:
    '''
    Универсальная сводка по CSV.
    Работает даже тогда, когда в файле нет специальных колонок метрик.
    '''
    rows = []

    for col in df.columns:
        series = df[col]

        if pd.api.types.is_numeric_dtype(series):
            rows.append(
                {
                    "column": col,
                    "count": int(series.count()),
                    "mean": float(series.mean()) if series.count() else None,
                    "min": float(series.min()) if series.count() else None,
                    "max": float(series.max()) if series.count() else None,
                }
            )

    return pd.DataFrame(rows)
