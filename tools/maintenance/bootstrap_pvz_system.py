from pathlib import Path
import textwrap
import json


ROOT = Path.cwd()


def write_file(path: str, content: str, overwrite: bool = False) -> None:
    file_path = ROOT / path
    file_path.parent.mkdir(parents=True, exist_ok=True)

    if file_path.exists() and not overwrite:
        print(f"[skip] {path} уже существует")
        return

    file_path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
    print(f"[ok] создан файл: {path}")


def write_json(path: str, data: dict, overwrite: bool = False) -> None:
    file_path = ROOT / path
    file_path.parent.mkdir(parents=True, exist_ok=True)

    if file_path.exists() and not overwrite:
        print(f"[skip] {path} уже существует")
        return

    file_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"[ok] создан файл: {path}")


def main() -> None:
    print("=== PVZ System Bootstrap ===")
    print(f"Корень проекта: {ROOT}")

    write_json(
        "configs/moscow_demo.json",
        {
            "project_name": "PVZ Moscow Location Optimization",
            "description": "Программная система выбора и анализа локаций ПВЗ в Москве",
            "paths": {
                "models_dir": "pvz_project/models",
                "scripts_dir": "scripts/final",
                "artifacts_dir": "pvz_project/deliverables/thesis_artifacts",
                "outputs_dir": "outputs"
            },
            "demo": {
                "default_k": 20,
                "default_model": "coverage"
            },
            "model_aliases": {
                "coverage": [
                    "coverage",
                    "maxcoverage",
                    "max_coverage",
                    "greedy"
                ],
                "mean_time": [
                    "mean",
                    "min_mean",
                    "mean_time",
                    "time"
                ],
                "effective": [
                    "effective",
                    "eff",
                    "max_effective"
                ],
                "compromise": [
                    "compromise",
                    "zelenograd",
                    "keep_zelenogra",
                    "limited"
                ]
            }
        },
        overwrite=False
    )

    write_file(
        "requirements-app.txt",
        """
        streamlit>=1.30.0
        pandas>=2.0.0
        numpy>=1.24.0
        plotly>=5.18.0
        pydeck>=0.8.0
        """,
        overwrite=False
    )

    write_file(
        "main.py",
        """
        from pvz_system.cli import main


        if __name__ == "__main__":
            main()
        """,
        overwrite=False
    )

    write_file(
        "app.py",
        """
        from pvz_system.interface.dashboard import run_dashboard


        if __name__ == "__main__":
            run_dashboard()
        """,
        overwrite=False
    )

    write_file(
        "pvz_system/__init__.py",
        """
        __version__ = "0.1.0"
        """,
        overwrite=False
    )

    write_file(
        "pvz_system/config.py",
        """
        from dataclasses import dataclass
        from pathlib import Path
        import json


        @dataclass
        class ProjectConfig:
            project_name: str
            description: str
            root_dir: Path
            models_dir: Path
            scripts_dir: Path
            artifacts_dir: Path
            outputs_dir: Path
            default_k: int
            default_model: str
            model_aliases: dict


        def load_config(config_path: str = "configs/moscow_demo.json") -> ProjectConfig:
            root_dir = Path.cwd()
            path = root_dir / config_path

            if not path.exists():
                raise FileNotFoundError(
                    f"Не найден конфигурационный файл: {path}. "
                    f"Сначала запустите bootstrap_pvz_system.py"
                )

            raw = json.loads(path.read_text(encoding="utf-8"))
            paths = raw.get("paths", {})
            demo = raw.get("demo", {})

            return ProjectConfig(
                project_name=raw.get("project_name", "PVZ Location System"),
                description=raw.get("description", ""),
                root_dir=root_dir,
                models_dir=root_dir / paths.get("models_dir", "pvz_project/models"),
                scripts_dir=root_dir / paths.get("scripts_dir", "scripts/final"),
                artifacts_dir=root_dir / paths.get(
                    "artifacts_dir",
                    "pvz_project/deliverables/thesis_artifacts"
                ),
                outputs_dir=root_dir / paths.get("outputs_dir", "outputs"),
                default_k=int(demo.get("default_k", 20)),
                default_model=demo.get("default_model", "coverage"),
                model_aliases=raw.get("model_aliases", {})
            )
        """,
        overwrite=False
    )

    write_file(
        "pvz_system/data_io.py",
        """
        from pathlib import Path
        from typing import Optional
        import pandas as pd

        from pvz_system.config import ProjectConfig


        def find_csv_files(directory: Path) -> list[Path]:
            if not directory.exists():
                return []
            return sorted(directory.rglob("*.csv"))


        def list_available_models(config: ProjectConfig) -> list[Path]:
            return find_csv_files(config.models_dir)


        def _normalize_name(path: Path) -> str:
            return path.name.lower().replace("-", "_")


        def find_model_file(config: ProjectConfig, model_name: str) -> Optional[Path]:
            model_name = model_name.lower().strip()
            csv_files = list_available_models(config)

            if not csv_files:
                return None

            aliases = config.model_aliases.get(model_name, [model_name])
            aliases = [a.lower().strip() for a in aliases]

            candidates: list[Path] = []

            for file in csv_files:
                name = _normalize_name(file)
                if any(alias in name for alias in aliases):
                    candidates.append(file)

            if not candidates:
                return None

            # Предпочитаем файлы с k20, так как в работе основной сценарий K = 20.
            k20 = [p for p in candidates if "k20" in _normalize_name(p)]
            if k20:
                return k20[0]

            return candidates[0]


        def read_model_dataframe(config: ProjectConfig, model_name: str) -> pd.DataFrame:
            file_path = find_model_file(config, model_name)

            if file_path is None:
                available = "\\n".join(str(p) for p in list_available_models(config))
                raise FileNotFoundError(
                    f"Не удалось найти CSV для модели '{model_name}'.\\n"
                    f"Папка поиска: {config.models_dir}\\n"
                    f"Найденные CSV:\\n{available}"
                )

            return pd.read_csv(file_path)


        def detect_coordinate_columns(df: pd.DataFrame) -> tuple[Optional[str], Optional[str]]:
            columns = {col.lower(): col for col in df.columns}

            lon_candidates = [
                "lon", "lng", "longitude", "x", "candidate_lon", "geometry_x"
            ]
            lat_candidates = [
                "lat", "latitude", "y", "candidate_lat", "geometry_y"
            ]

            lon_col = None
            lat_col = None

            for name in lon_candidates:
                if name in columns:
                    lon_col = columns[name]
                    break

            for name in lat_candidates:
                if name in columns:
                    lat_col = columns[name]
                    break

            return lat_col, lon_col
        """,
        overwrite=False
    )

    write_file(
        "pvz_system/evaluation/__init__.py",
        """
        """,
        overwrite=False
    )

    write_file(
        "pvz_system/evaluation/metrics.py",
        """
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
        """,
        overwrite=False
    )

    write_file(
        "pvz_system/optimization/__init__.py",
        """
        """,
        overwrite=False
    )

    write_file(
        "pvz_system/optimization/greedy.py",
        """
        import numpy as np


        def greedy_max_coverage(
            access_matrix: np.ndarray,
            demand_weights: np.ndarray,
            k: int,
            threshold: float = 10.0,
        ) -> list[int]:
            '''
            Жадный алгоритм максимизации охвата.

            access_matrix[i, j] — время доступа от точки спроса i
            до кандидатной локации j.

            demand_weights[i] — вес спроса в точке i.

            Возвращает индексы выбранных кандидатов.
            '''
            n_demand, n_candidates = access_matrix.shape

            selected: list[int] = []
            covered = np.zeros(n_demand, dtype=bool)
            remaining = set(range(n_candidates))

            for _ in range(k):
                best_candidate = None
                best_gain = -1.0

                for candidate in remaining:
                    new_covered = covered | (access_matrix[:, candidate] <= threshold)
                    gain = demand_weights[new_covered & ~covered].sum()

                    if gain > best_gain:
                        best_gain = gain
                        best_candidate = candidate

                if best_candidate is None:
                    break

                selected.append(best_candidate)
                remaining.remove(best_candidate)
                covered = covered | (access_matrix[:, best_candidate] <= threshold)

            return selected


        def greedy_min_mean_time(
            access_matrix: np.ndarray,
            demand_weights: np.ndarray,
            k: int,
        ) -> list[int]:
            '''
            Жадный алгоритм минимизации среднего времени доступа.
            '''
            n_demand, n_candidates = access_matrix.shape

            selected: list[int] = []
            remaining = set(range(n_candidates))
            current_best_times = np.full(n_demand, np.inf)

            for _ in range(k):
                best_candidate = None
                best_score = np.inf

                for candidate in remaining:
                    candidate_times = np.minimum(
                        current_best_times,
                        access_matrix[:, candidate]
                    )
                    score = np.average(candidate_times, weights=demand_weights)

                    if score < best_score:
                        best_score = score
                        best_candidate = candidate

                if best_candidate is None:
                    break

                selected.append(best_candidate)
                remaining.remove(best_candidate)
                current_best_times = np.minimum(
                    current_best_times,
                    access_matrix[:, best_candidate]
                )

            return selected


        def greedy_max_effective_demand(
            access_matrix: np.ndarray,
            demand_weights: np.ndarray,
            k: int,
            tau: float = 10.0,
        ) -> list[int]:
            '''
            Жадный алгоритм максимизации эффективного спроса.
            Используется функция полезности exp(-t / tau).
            '''
            n_demand, n_candidates = access_matrix.shape

            selected: list[int] = []
            remaining = set(range(n_candidates))
            current_best_times = np.full(n_demand, np.inf)

            for _ in range(k):
                best_candidate = None
                best_score = -np.inf

                for candidate in remaining:
                    candidate_times = np.minimum(
                        current_best_times,
                        access_matrix[:, candidate]
                    )
                    utility = np.exp(-candidate_times / tau)
                    score = np.average(utility, weights=demand_weights)

                    if score > best_score:
                        best_score = score
                        best_candidate = candidate

                if best_candidate is None:
                    break

                selected.append(best_candidate)
                remaining.remove(best_candidate)
                current_best_times = np.minimum(
                    current_best_times,
                    access_matrix[:, best_candidate]
                )

            return selected
        """,
        overwrite=False
    )

    write_file(
        "pvz_system/interface/__init__.py",
        """
        """,
        overwrite=False
    )

    write_file(
        "pvz_system/interface/dashboard.py",
        """
        from pathlib import Path

        import pandas as pd
        import streamlit as st

        try:
            import pydeck as pdk
        except Exception:
            pdk = None

        from pvz_system.config import load_config
        from pvz_system.data_io import (
            list_available_models,
            find_model_file,
            read_model_dataframe,
            detect_coordinate_columns,
        )
        from pvz_system.evaluation.metrics import summarize_result_table


        MODEL_LABELS = {
            "coverage": "Максимизация охвата",
            "mean_time": "Минимизация среднего времени",
            "effective": "Максимизация эффективного спроса",
            "compromise": "Ограниченная компромиссная модель",
        }


        def _show_map(df: pd.DataFrame) -> None:
            lat_col, lon_col = detect_coordinate_columns(df)

            if not lat_col or not lon_col:
                st.info(
                    "В выбранном CSV не найдены координатные колонки. "
                    "Ожидаемые названия: lat/lon, latitude/longitude, x/y."
                )
                return

            map_df = df[[lat_col, lon_col]].dropna().copy()
            map_df = map_df.rename(columns={lat_col: "lat", lon_col: "lon"})

            if map_df.empty:
                st.info("Координатные колонки найдены, но в них нет данных.")
                return

            st.map(map_df)

            if pdk is not None:
                st.caption("Карта построена по координатам выбранных ПВЗ.")


        def run_dashboard() -> None:
            st.set_page_config(
                page_title="PVZ Location System",
                layout="wide"
            )

            config = load_config()

            st.title("Система выбора локаций ПВЗ в Москве")
            st.caption(
                "Демонстрационный интерфейс к GIS-пайплайну: "
                "модели размещения, готовые конфигурации, таблицы и карты."
            )

            with st.sidebar:
                st.header("Параметры демонстрации")

                model_name = st.selectbox(
                    "Модель размещения",
                    options=list(MODEL_LABELS.keys()),
                    format_func=lambda key: MODEL_LABELS[key],
                    index=list(MODEL_LABELS.keys()).index(config.default_model)
                    if config.default_model in MODEL_LABELS else 0,
                )

                k = st.number_input(
                    "Число ПВЗ K",
                    min_value=1,
                    max_value=200,
                    value=config.default_k,
                    step=1,
                )

                st.divider()

                st.write("Папка моделей:")
                st.code(str(config.models_dir))

            st.subheader("Описание системы")

            st.markdown(
                '''
                Программная система реализует полный цикл исследования:
                подготовку пространственных данных, построение пешеходного графа,
                формирование модели потенциального спроса, генерацию кандидатных
                локаций, запуск моделей размещения и сравнение полученных решений.

                В демонстрационном режиме интерфейс работает с уже рассчитанными
                CSV-файлами из папки `pvz_project/models`.
                '''
            )

            available_files = list_available_models(config)

            with st.expander("Найденные CSV-файлы с результатами"):
                if available_files:
                    for file in available_files:
                        st.write(file.relative_to(config.root_dir))
                else:
                    st.warning("CSV-файлы в папке моделей не найдены.")

            st.subheader("Результат выбранной модели")

            file_path = find_model_file(config, model_name)

            if file_path is None:
                st.error(
                    f"Не найден CSV-файл для модели: {MODEL_LABELS[model_name]}"
                )
                st.stop()

            st.write("Используемый файл:")
            st.code(str(file_path.relative_to(config.root_dir)))

            try:
                df = read_model_dataframe(config, model_name)
            except Exception as exc:
                st.exception(exc)
                st.stop()

            col1, col2 = st.columns([2, 1])

            with col1:
                st.markdown("#### Таблица выбранных локаций / результатов")
                st.dataframe(df, use_container_width=True)

            with col2:
                st.markdown("#### Общая информация")
                st.metric("Строк в файле", len(df))
                st.metric("Колонок в файле", len(df.columns))
                st.metric("Заданное K", int(k))

                st.markdown("#### Колонки")
                st.write(", ".join(df.columns.astype(str)))

            st.markdown("#### Карта")
            _show_map(df)

            st.markdown("#### Числовая сводка")
            summary = summarize_result_table(df)

            if summary.empty:
                st.info("В таблице нет числовых колонок для сводки.")
            else:
                st.dataframe(summary, use_container_width=True)

            st.subheader("Как демонстрировать на защите")

            st.markdown(
                '''
                1. Выбрать модель размещения в левом меню.
                2. Показать, что система автоматически находит соответствующий CSV.
                3. Продемонстрировать таблицу выбранных локаций.
                4. Показать карту, если в данных есть координаты.
                5. Перейти к сравнению моделей и объяснить, что разные критерии
                   дают разные пространственные конфигурации сети.
                '''
            )
        """,
        overwrite=False
    )

    write_file(
        "pvz_system/cli.py",
        """
        import argparse
        import sys

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

            if model_name not in MODEL_NAMES:
                print(f"Неизвестная модель: {model_name}")
                print(f"Доступные модели: {', '.join(MODEL_NAMES)}")
                sys.exit(1)

            file_path = find_model_file(config, model_name)

            if file_path is None:
                print(f"CSV для модели '{model_name}' не найден.")
                print(f"Папка поиска: {config.models_dir}")
                sys.exit(1)

            print(f"Модель: {model_name}")
            print(f"Файл: {file_path.relative_to(config.root_dir)}")
            print()

            df = read_model_dataframe(config, model_name)

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

            return parser


        def main() -> None:
            parser = build_parser()
            args = parser.parse_args()
            args.func(args)
        """,
        overwrite=False
    )

    write_file(
        "docs/ARCHITECTURE.md",
        """
        # Архитектура программной системы

        Проект оформляется как программная система поддержки принятия решений
        для выбора локаций пунктов выдачи заказов на территории Москвы.

        ## Общая логика

        Система реализует воспроизводимый GIS-пайплайн:

        1. подготовка исходных пространственных данных;
        2. построение пешеходного графа;
        3. формирование модели потенциального спроса;
        4. генерация множества кандидатных локаций;
        5. запуск моделей оптимизационного размещения;
        6. расчёт городских и районных метрик;
        7. визуализация результатов;
        8. сравнение конфигураций сети.

        ## Основные модули

        - `pvz_system.config` — загрузка конфигурации проекта;
        - `pvz_system.data_io` — поиск и чтение готовых CSV-файлов;
        - `pvz_system.optimization` — алгоритмическое ядро жадной оптимизации;
        - `pvz_system.evaluation` — расчёт и сводка метрик;
        - `pvz_system.interface` — демонстрационный Streamlit-интерфейс;
        - `main.py` — консольная точка входа;
        - `app.py` — запуск демонстрационного интерфейса.

        ## Режимы работы

        ### Исследовательский режим

        Используется полный набор скриптов из `scripts/final`.
        Он предназначен для подготовки данных, построения графа,
        расчёта моделей и формирования итоговых артефактов.

        ### Демонстрационный режим

        Используется для защиты и быстрого просмотра результатов.
        Интерфейс считывает уже рассчитанные CSV-файлы из `pvz_project/models`
        и показывает таблицы, карты и числовые сводки.

        Такой подход снижает риск долгих вычислений во время демонстрации,
        но сохраняет воспроизводимость полного расчётного пайплайна.
        """,
        overwrite=False
    )

    write_file(
        "docs/DEFENSE_PROGRAM_BLOCK.md",
        """
        # Блок для презентации: программная реализация

        ## Слайд 1. Назначение программной системы

        Разработанная программная система предназначена для выбора и анализа
        локаций пунктов выдачи заказов в Москве на основе открытых
        пространственных данных, пешеходной доступности и моделей
        оптимизационного размещения.

        Система реализует полный цикл вычислительного эксперимента:
        от подготовки геоданных до сравнения итоговых конфигураций сети.

        ## Слайд 2. Архитектура

        В системе выделены следующие модули:

        - подготовка пространственных данных;
        - построение пешеходного графа;
        - формирование модели потенциального спроса;
        - генерация кандидатных локаций;
        - оптимизационное размещение ПВЗ;
        - расчёт метрик качества;
        - визуализация и сравнение результатов.

        ## Слайд 3. Входные и выходные данные

        Входные данные:

        - OpenStreetMap;
        - административные границы Москвы;
        - параметры модели;
        - число размещаемых ПВЗ;
        - выбранный критерий оптимизации.

        Выходные данные:

        - выбранные локации ПВЗ;
        - таблицы городских и районных метрик;
        - карты размещения;
        - карты изменения показателей;
        - графики насыщения сети;
        - сравнительные панели.

        ## Слайд 4. Реализованные модели

        В системе реализованы четыре модели:

        1. максимизация охвата спроса в пределах 10 минут;
        2. минимизация среднего времени доступа;
        3. максимизация эффективного спроса;
        4. ограниченная компромиссная модель с сохранением удалённого кластера.

        ## Слайд 5. Демонстрационный интерфейс

        Для демонстрации реализован интерфейс, позволяющий:

        - выбрать модель размещения;
        - задать число ПВЗ;
        - открыть рассчитанную конфигурацию;
        - просмотреть таблицу результатов;
        - отобразить выбранные точки на карте;
        - получить числовую сводку по результату.

        ## Слайд 6. Практическая ценность реализации

        Программная система позволяет не только получить одну конфигурацию
        сети, но и сравнить разные стратегии размещения ПВЗ по единой
        системе показателей.

        Это делает разработку инструментом предварительного пространственного
        отбора локаций и поддержки принятия решений при развитии сети ПВЗ.
        """,
        overwrite=False
    )

    write_file(
        "README.md",
        """
        # PVZ Moscow Location Optimization

        Проект представляет собой исследование и программную реализацию методов
        выбора локаций пунктов выдачи заказов на территории Москвы с использованием
        открытых пространственных данных, модели пешеходной доступности и алгоритмов
        пространственной оптимизации.

        Работа выполнена как воспроизводимый GIS-пайплайн: от подготовки исходных
        геоданных до построения, оценки и сравнения нескольких конфигураций сети ПВЗ
        по различным критериям качества.

        ## Что реализовано

        В проекте реализованы:

        - подготовка пространственных данных;
        - построение пешеходного графа Москвы;
        - формирование модели потенциального спроса на основе жилой застройки;
        - генерация множества кандидатных локаций;
        - модель максимизации охвата;
        - модель минимизации среднего времени доступа;
        - модель максимизации эффективного спроса;
        - ограниченная компромиссная модель;
        - сравнение решений по городским и районным метрикам;
        - построение карт, графиков и итоговых визуализаций.

        ## Программная оболочка

        Помимо исследовательских скриптов, проект оформлен как программная система
        с единой точкой запуска и демонстрационным интерфейсом.

        Основные файлы:

        - `main.py` — консольный запуск;
        - `app.py` — запуск демонстрационного интерфейса;
        - `pvz_system/` — модульная оболочка проекта;
        - `configs/moscow_demo.json` — конфигурация путей и моделей;
        - `docs/ARCHITECTURE.md` — описание архитектуры;
        - `docs/DEFENSE_PROGRAM_BLOCK.md` — материал для слайдов защиты.

        ## Установка

        ```bash
        pip install -r requirements.txt
        pip install -r requirements-app.txt
        ```

        ## Проверка проекта

        ```bash
        python main.py status
        ```

        ## Просмотр найденных моделей

        ```bash
        python main.py list-models
        ```

        ## Просмотр результата отдельной модели

        ```bash
        python main.py show-model coverage
        python main.py show-model mean_time
        python main.py show-model effective
        python main.py show-model compromise
        ```

        ## Запуск интерфейса

        ```bash
        streamlit run app.py
        ```

        ## Модели размещения

        В проекте сравниваются четыре модели:

        1. **Максимизация охвата** — выбор точек, которые покрывают максимум
           потенциального спроса в пределах 10 минут пешком.

        2. **Минимизация среднего времени доступа** — выбор точек, сокращающих
           среднее время пути до ближайшего ПВЗ.

        3. **Максимизация эффективного спроса** — выбор точек, максимизирующих
           интегральную полезность сети с учётом постепенного снижения удобства
           при росте времени доступа.

        4. **Ограниченная компромиссная модель** — вариант, который сохраняет
           высокий интегральный результат, но дополнительно учитывает обслуживание
           удалённых территорий.

        ## Практический смысл

        Разработка позволяет сравнивать стратегии размещения ПВЗ не только по
        общегородским показателям, но и по распределению эффекта между районами
        Москвы. Это важно, поскольку модель, лучшая по одному критерию, может
        ухудшать положение отдельных территорий.

        Основной результат исследования состоит в том, что разные критерии
        оптимизации приводят к различным пространственным конфигурациям сети ПВЗ
        и различным компромиссам между охватом, временем доступа и интегральной
        полезностью сети.
        """,
        overwrite=False
    )

    print()
    print("=== Готово ===")
    print("Теперь можно выполнить:")
    print("  pip install -r requirements-app.txt")
    print("  python main.py status")
    print("  python main.py list-models")
    print("  streamlit run app.py")


if __name__ == "__main__":
    main()