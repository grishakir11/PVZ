from pathlib import Path
import pandas as pd

from pvz_system.data_io import (
    find_model_file,
    read_model_dataframe,
    detect_coordinate_columns,
    list_available_models,
)


MODEL_LABELS = {
    "coverage": "Максимизация охвата",
    "mean_time": "Минимизация среднего времени",
    "effective": "Максимизация эффективного спроса",
    "compromise": "Ограниченная компромиссная модель",
}


MODEL_DESCRIPTIONS = {
    "coverage": (
        "Выбор локаций, обеспечивающих максимальный прирост потенциального "
        "спроса в пределах 10 минут пешего доступа."
    ),
    "mean_time": (
        "Выбор локаций, которые сильнее всего сокращают среднее взвешенное "
        "время пешего доступа до ближайшего ПВЗ."
    ),
    "effective": (
        "Выбор локаций, максимизирующих интегральную полезность сети с учётом "
        "снижения привлекательности ПВЗ при росте времени пути."
    ),
    "compromise": (
        "Компромиссный вариант: часть точек фиксируется для сохранения "
        "обслуживания Зеленограда, остальные выбираются по эффективному спросу."
    ),
}


ZELENOGRAD_DISTRICTS = {
    "Матушкино",
    "Савёлки",
    "Савелки",
    "Силино",
    "Старое Крюково",
    "Крюково",
}


def sort_model_df(df: pd.DataFrame) -> pd.DataFrame:
    if "sel_rank" in df.columns:
        return df.sort_values("sel_rank").reset_index(drop=True)
    return df.reset_index(drop=True)


def load_model(config, model_name: str) -> tuple[pd.DataFrame | None, Path | None]:
    file_path = find_model_file(config, model_name)
    if file_path is None:
        return None, None

    df = read_model_dataframe(config, model_name)
    df = sort_model_df(df)
    return df, file_path


def load_all_models(config) -> dict[str, dict]:
    result = {}

    for model_name in MODEL_LABELS:
        df, file_path = load_model(config, model_name)
        result[model_name] = {
            "df": df,
            "file_path": file_path,
            "label": MODEL_LABELS[model_name],
            "description": MODEL_DESCRIPTIONS[model_name],
        }

    return result


def build_model_summary(config) -> pd.DataFrame:
    rows = []

    for model_name, item in load_all_models(config).items():
        df = item["df"]
        file_path = item["file_path"]

        if df is None:
            rows.append(
                {
                    "model": model_name,
                    "model_label": item["label"],
                    "file": "не найден",
                    "points": 0,
                    "unique_districts": 0,
                    "zelenograd_points": 0,
                    "fixed_points": 0,
                    "chosen_points": 0,
                }
            )
            continue

        if "district_name" in df.columns:
            districts = df["district_name"].dropna().astype(str)
            unique_districts = int(districts.nunique())
            zelenograd_points = int(districts.isin(ZELENOGRAD_DISTRICTS).sum())
        else:
            unique_districts = 0
            zelenograd_points = 0

        fixed_points = 0
        chosen_points = 0

        if "source" in df.columns:
            fixed_points = int(df["source"].astype(str).str.contains("fixed", case=False).sum())
            chosen_points = int(df["source"].astype(str).str.contains("chosen", case=False).sum())

        rows.append(
            {
                "model": model_name,
                "model_label": item["label"],
                "file": str(file_path.relative_to(config.root_dir)) if file_path else "не найден",
                "points": int(len(df)),
                "unique_districts": unique_districts,
                "zelenograd_points": zelenograd_points,
                "fixed_points": fixed_points,
                "chosen_points": chosen_points,
            }
        )

    return pd.DataFrame(rows)


def build_combined_points(config) -> pd.DataFrame:
    frames = []

    for model_name, item in load_all_models(config).items():
        df = item["df"]
        file_path = item["file_path"]

        if df is None:
            continue

        lat_col, lon_col = detect_coordinate_columns(df)
        if not lat_col or not lon_col:
            continue

        tmp = df.copy()
        tmp = tmp.rename(columns={lat_col: "lat", lon_col: "lon"})
        tmp["model"] = model_name
        tmp["model_label"] = item["label"]
        tmp["source_file"] = file_path.name if file_path else ""

        frames.append(tmp)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def _coord_set(df: pd.DataFrame) -> set[tuple[float, float]]:
    lat_col, lon_col = detect_coordinate_columns(df)

    if not lat_col or not lon_col:
        return set()

    points = df[[lat_col, lon_col]].dropna().copy()

    if points.empty:
        return set()

    return set(
        zip(
            points[lat_col].round(5).astype(float),
            points[lon_col].round(5).astype(float),
        )
    )


def build_overlap_matrix(config) -> pd.DataFrame:
    models = load_all_models(config)

    sets = {}
    for model_name, item in models.items():
        df = item["df"]
        sets[model_name] = _coord_set(df) if df is not None else set()

    matrix = []

    for row_model in MODEL_LABELS:
        row = {"model": MODEL_LABELS[row_model]}

        for col_model in MODEL_LABELS:
            row[MODEL_LABELS[col_model]] = len(sets[row_model] & sets[col_model])

        matrix.append(row)

    return pd.DataFrame(matrix)


def build_district_distribution(config) -> pd.DataFrame:
    combined = build_combined_points(config)

    if combined.empty or "district_name" not in combined.columns:
        return pd.DataFrame()

    return (
        combined
        .groupby(["model_label", "district_name"])
        .size()
        .reset_index(name="points")
        .sort_values(["model_label", "points"], ascending=[True, False])
    )


def list_artifacts(config) -> list[Path]:
    root = config.artifacts_dir

    if not root.exists():
        return []

    allowed = {
        ".png", ".jpg", ".jpeg", ".webp", ".svg",
        ".csv", ".xlsx", ".html", ".pdf"
    }

    return sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in allowed
    )


def list_scripts(config) -> list[Path]:
    if not config.scripts_dir.exists():
        return []
    return sorted(config.scripts_dir.glob("*.py"))


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_Нет данных._"

    columns = list(df.columns)
    lines = []

    lines.append("| " + " | ".join(columns) + " |")
    lines.append("| " + " | ".join(["---"] * len(columns)) + " |")

    for _, row in df.iterrows():
        values = [str(row[col]) for col in columns]
        lines.append("| " + " | ".join(values) + " |")

    return "\n".join(lines)


def make_markdown_report(config) -> str:
    summary = build_model_summary(config)
    overlap = build_overlap_matrix(config)
    artifacts = list_artifacts(config)
    scripts = list_scripts(config)

    lines = [
        "# Отчёт по программной системе выбора локаций ПВЗ",
        "",
        "## Назначение",
        "",
        (
            "Система реализует воспроизводимый GIS-пайплайн для выбора "
            "и анализа локаций пунктов выдачи заказов в Москве. "
            "Она объединяет подготовку пространственных данных, построение "
            "модели спроса, запуск моделей размещения и визуализацию результатов."
        ),
        "",
        "## Реализованные модели",
        "",
    ]

    for model_name, label in MODEL_LABELS.items():
        lines.append(f"### {label}")
        lines.append("")
        lines.append(MODEL_DESCRIPTIONS[model_name])
        lines.append("")

    lines.extend(
        [
            "## Сводка по рассчитанным конфигурациям",
            "",
            markdown_table(summary),
            "",
            "## Пересечение выбранных локаций между моделями",
            "",
            (
                "Значения показывают количество совпадающих точек между "
                "конфигурациями. Координаты сравниваются с округлением."
            ),
            "",
            markdown_table(overlap),
            "",
            "## Расчётный pipeline",
            "",
            f"Количество финальных скриптов: {len(scripts)}.",
            "",
        ]
    )

    for idx, script in enumerate(scripts, start=1):
        lines.append(f"{idx}. `{script.relative_to(config.root_dir)}`")

    lines.extend(
        [
            "",
            "## Итоговые артефакты",
            "",
            f"Количество найденных артефактов: {len(artifacts)}.",
            "",
        ]
    )

    for artifact in artifacts[:30]:
        lines.append(f"- `{artifact.relative_to(config.root_dir)}`")

    if len(artifacts) > 30:
        lines.append(f"- ... и ещё {len(artifacts) - 30} файлов")

    lines.extend(
        [
            "",
            "## Вывод для защиты",
            "",
            (
                "Программная реализация оформляет исследовательские расчёты "
                "в виде модульной системы. Это позволяет не только получить "
                "одну конфигурацию ПВЗ, но и сравнивать несколько стратегий "
                "размещения по единой системе показателей и показывать "
                "результаты в демонстрационном интерфейсе."
            ),
            "",
        ]
    )

    return "\n".join(lines)
