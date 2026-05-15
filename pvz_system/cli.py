import argparse
import sys
import pandas as pd

from pvz_system.config import load_config
from pvz_system.data_io import (
    list_available_models,
    find_model_file,
    read_model_dataframe,
)
from pvz_system.evaluation.metrics import summarize_result_table


MODEL_NAMES = ["coverage", "mean_time", "effective", "compromise"]


def command_status(args) -> None:
    config = load_config(args.config)

    print("PVZ Location System")
    print("=" * 60)
    print(f"Название: {config.project_name}")
    print(f"Описание: {config.description}")
    print(f"Корень проекта: {config.root_dir}")
    print(f"Папка моделей: {config.models_dir}")
    print(f"Папка финальных скриптов: {config.scripts_dir}")
    print(f"Папка артефактов: {config.artifacts_dir}")
    print(f"Папка выходных файлов: {config.outputs_dir}")
    print()

    print("Проверка существования путей:")
    for label, path in [
        ("models_dir", config.models_dir),
        ("scripts_dir", config.scripts_dir),
        ("artifacts_dir", config.artifacts_dir),
        ("outputs_dir", config.outputs_dir),
    ]:
        status = "OK" if path.exists() else "НЕ НАЙДЕНО"
        print(f"  {label}: {status} — {path}")


def command_list_models(args) -> None:
    config = load_config(args.config)
    files = list_available_models(config)

    print("Найденные CSV-файлы моделей:")
    if not files:
        print("  CSV-файлы не найдены")
        return

    for file in files:
        print(f"  - {file.relative_to(config.root_dir)}")


def command_show_model(args) -> None:
    config = load_config(args.config)
    model_name = args.model

    file_path = find_model_file(config, model_name)

    if file_path is None:
        print(f"CSV для модели '{model_name}' не найден.")
        print(f"Папка поиска: {config.models_dir}")
        sys.exit(1)

    print(f"Модель: {model_name}")
    print(f"Файл: {file_path.relative_to(config.root_dir)}")
    print()

    df = read_model_dataframe(config, model_name)

    if "sel_rank" in df.columns:
        df = df.sort_values("sel_rank")

    print("Размер таблицы:")
    print(f"  строк: {len(df)}")
    print(f"  колонок: {len(df.columns)}")
    print()

    print("Колонки:")
    for col in df.columns:
        print(f"  - {col}")
    print()

    print("Первые строки:")
    print(df.head(args.head).to_string(index=False))
    print()

    summary = summarize_result_table(df)

    if not summary.empty:
        print("Числовая сводка:")
        print(summary.to_string(index=False))


def command_compare_models(args) -> None:
    config = load_config(args.config)

    rows = []

    for model_name in MODEL_NAMES:
        file_path = find_model_file(config, model_name)

        if file_path is None:
            rows.append(
                {
                    "model": model_name,
                    "file": "NOT FOUND",
                    "rows": None,
                    "columns": None,
                    "unique_districts": None,
                    "zelenograd_points": None,
                }
            )
            continue

        df = read_model_dataframe(config, model_name)

        zelenograd_names = {
            "Матушкино",
            "Савёлки",
            "Савелки",
            "Силино",
            "Старое Крюково",
            "Крюково",
        }

        if "district_name" in df.columns:
            districts = df["district_name"].dropna().astype(str)
            unique_districts = districts.nunique()
            zelenograd_points = int(districts.isin(zelenograd_names).sum())
        else:
            unique_districts = None
            zelenograd_points = None

        rows.append(
            {
                "model": model_name,
                "file": str(file_path.relative_to(config.root_dir)),
                "rows": len(df),
                "columns": len(df.columns),
                "unique_districts": unique_districts,
                "zelenograd_points": zelenograd_points,
            }
        )

    result = pd.DataFrame(rows)
    print(result.to_string(index=False))


def command_list_artifacts(args) -> None:
    config = load_config(args.config)

    if not config.artifacts_dir.exists():
        print(f"Папка артефактов не найдена: {config.artifacts_dir}")
        return

    files = sorted(path for path in config.artifacts_dir.rglob("*") if path.is_file())

    if not files:
        print("Артефакты не найдены.")
        return

    print("Артефакты исследования:")
    for file in files:
        print(f"  - {file.relative_to(config.root_dir)}")


def command_list_scripts(args) -> None:
    config = load_config(args.config)

    if not config.scripts_dir.exists():
        print(f"Папка финальных скриптов не найдена: {config.scripts_dir}")
        return

    scripts = sorted(config.scripts_dir.glob("*.py"))

    if not scripts:
        print("Финальные скрипты не найдены.")
        return

    print("Финальные скрипты pipeline:")
    for idx, script in enumerate(scripts, start=1):
        print(f"{idx:02d}. {script.relative_to(config.root_dir)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PVZ Location System — оболочка GIS-пайплайна размещения ПВЗ"
    )

    parser.add_argument(
        "--config",
        default="configs/moscow_demo.json",
        help="Путь к конфигурационному файлу"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser(
        "status",
        help="Проверить структуру проекта"
    )
    status_parser.set_defaults(func=command_status)

    list_parser = subparsers.add_parser(
        "list-models",
        help="Показать найденные CSV-файлы с результатами моделей"
    )
    list_parser.set_defaults(func=command_list_models)

    show_parser = subparsers.add_parser(
        "show-model",
        help="Показать данные по выбранной модели"
    )
    show_parser.add_argument(
        "model",
        choices=MODEL_NAMES,
        help="Название модели"
    )
    show_parser.add_argument(
        "--head",
        type=int,
        default=10,
        help="Сколько строк показать"
    )
    show_parser.set_defaults(func=command_show_model)

    compare_parser = subparsers.add_parser(
        "compare-models",
        help="Сравнить доступные модели по составу CSV"
    )
    compare_parser.set_defaults(func=command_compare_models)

    artifacts_parser = subparsers.add_parser(
        "list-artifacts",
        help="Показать итоговые артефакты исследования"
    )
    artifacts_parser.set_defaults(func=command_list_artifacts)

    scripts_parser = subparsers.add_parser(
        "list-scripts",
        help="Показать финальные скрипты pipeline"
    )
    scripts_parser.set_defaults(func=command_list_scripts)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
