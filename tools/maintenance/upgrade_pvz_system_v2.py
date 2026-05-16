from pathlib import Path
import textwrap


ROOT = Path.cwd()


def write_file(path: str, content: str) -> None:
    file_path = ROOT / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
    print(f"[ok] обновлён файл: {path}")


def main() -> None:
    print("=== PVZ System Upgrade v2 ===")

    write_file(
        "pvz_system/interface/dashboard.py",
        r'''
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


        MODEL_DESCRIPTIONS = {
            "coverage": (
                "Модель выбирает точки, которые дают максимальный прирост "
                "потенциального спроса в пределах 10 минут пешего доступа."
            ),
            "mean_time": (
                "Модель выбирает точки, которые сильнее всего сокращают среднее "
                "взвешенное время пешего доступа до ближайшего ПВЗ."
            ),
            "effective": (
                "Модель максимизирует интегральную полезность сети: вклад спроса "
                "постепенно снижается при увеличении времени пути."
            ),
            "compromise": (
                "Модель сохраняет обслуживание удалённого кластера Зеленограда, "
                "а оставшиеся точки выбирает по критерию эффективного спроса."
            ),
        }


        MODEL_COLORS = {
            "coverage": [220, 80, 80, 180],
            "mean_time": [80, 140, 230, 180],
            "effective": [80, 180, 120, 180],
            "compromise": [180, 110, 220, 180],
        }


        ZELENOGRAD_DISTRICTS = {
            "Матушкино",
            "Савёлки",
            "Савелки",
            "Силино",
            "Старое Крюково",
            "Крюково",
        }


        def sort_by_rank(df: pd.DataFrame) -> pd.DataFrame:
            if "sel_rank" in df.columns:
                return df.sort_values("sel_rank").reset_index(drop=True)
            return df.reset_index(drop=True)


        def load_model_safe(config, model_name: str) -> tuple[pd.DataFrame | None, Path | None, str | None]:
            try:
                file_path = find_model_file(config, model_name)
                if file_path is None:
                    return None, None, f"CSV-файл для модели '{model_name}' не найден."
                df = read_model_dataframe(config, model_name)
                df = sort_by_rank(df)
                return df, file_path, None
            except Exception as exc:
                return None, None, str(exc)


        def model_summary(df: pd.DataFrame, model_name: str) -> dict:
            districts = []
            if "district_name" in df.columns:
                districts = df["district_name"].dropna().astype(str).tolist()

            zelenograd_count = sum(1 for d in districts if d in ZELENOGRAD_DISTRICTS)

            source_counts = {}
            if "source" in df.columns:
                source_counts = df["source"].fillna("unknown").value_counts().to_dict()

            return {
                "model": model_name,
                "model_label": MODEL_LABELS.get(model_name, model_name),
                "points": int(len(df)),
                "unique_districts": int(df["district_name"].nunique()) if "district_name" in df.columns else None,
                "zelenograd_points": int(zelenograd_count),
                "has_source": "source" in df.columns,
                "source_counts": source_counts,
            }


        def render_single_map(df: pd.DataFrame) -> None:
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

            st.map(map_df, latitude="lat", longitude="lon")


        def build_combined_models_df(config) -> pd.DataFrame:
            frames = []

            for model_name in MODEL_LABELS:
                df, file_path, error = load_model_safe(config, model_name)
                if df is None:
                    continue

                lat_col, lon_col = detect_coordinate_columns(df)
                if not lat_col or not lon_col:
                    continue

                tmp = df.copy()
                tmp = tmp.rename(columns={lat_col: "lat", lon_col: "lon"})
                tmp["model"] = model_name
                tmp["model_label"] = MODEL_LABELS[model_name]
                tmp["color"] = [MODEL_COLORS[model_name]] * len(tmp)
                tmp["source_file"] = str(file_path.name) if file_path else ""
                frames.append(tmp)

            if not frames:
                return pd.DataFrame()

            return pd.concat(frames, ignore_index=True)


        def render_combined_map(combined_df: pd.DataFrame) -> None:
            if combined_df.empty:
                st.warning("Нет данных с координатами для построения общей карты.")
                return

            if pdk is None:
                st.map(combined_df, latitude="lat", longitude="lon")
                return

            center_lat = float(combined_df["lat"].mean())
            center_lon = float(combined_df["lon"].mean())

            tooltip = {
                "html": (
                    "<b>{model_label}</b><br/>"
                    "Район: {district_name}<br/>"
                    "Ранг: {sel_rank}<br/>"
                    "Файл: {source_file}"
                ),
                "style": {"backgroundColor": "white", "color": "black"},
            }

            layer = pdk.Layer(
                "ScatterplotLayer",
                data=combined_df,
                get_position="[lon, lat]",
                get_fill_color="color",
                get_radius=350,
                pickable=True,
                auto_highlight=True,
            )

            deck = pdk.Deck(
                map_style=None,
                initial_view_state=pdk.ViewState(
                    latitude=center_lat,
                    longitude=center_lon,
                    zoom=9,
                    pitch=0,
                ),
                layers=[layer],
                tooltip=tooltip,
            )

            st.pydeck_chart(deck)


        def list_artifact_files(root: Path) -> list[Path]:
            if not root.exists():
                return []

            extensions = {
                ".png", ".jpg", ".jpeg", ".webp", ".svg",
                ".csv", ".xlsx", ".html", ".pdf"
            }

            return sorted(
                path for path in root.rglob("*")
                if path.is_file() and path.suffix.lower() in extensions
            )


        def render_artifact_preview(path: Path) -> None:
            suffix = path.suffix.lower()

            if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                st.image(str(path), use_container_width=True)
            elif suffix == ".svg":
                st.image(str(path), use_container_width=True)
            elif suffix == ".csv":
                try:
                    df = pd.read_csv(path)
                    st.dataframe(df, use_container_width=True)
                except Exception as exc:
                    st.error(f"Не удалось прочитать CSV: {exc}")
            else:
                st.info("Для этого типа файла доступен только путь к артефакту.")
                st.code(str(path))


        def run_dashboard() -> None:
            st.set_page_config(
                page_title="PVZ Location System",
                layout="wide",
            )

            config = load_config()

            st.title("Система выбора локаций ПВЗ в Москве")
            st.caption(
                "Демонстрационная панель к воспроизводимому GIS-пайплайну: "
                "модели размещения, карты, таблицы, сравнение и артефакты исследования."
            )

            with st.sidebar:
                st.header("Параметры")

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

                st.markdown("**Папка моделей**")
                st.code(str(config.models_dir))

                st.markdown("**Папка артефактов**")
                st.code(str(config.artifacts_dir))

            tab_about, tab_model, tab_compare, tab_artifacts, tab_pipeline = st.tabs(
                [
                    "О системе",
                    "Выбранная модель",
                    "Сравнение моделей",
                    "Артефакты",
                    "Pipeline",
                ]
            )

            with tab_about:
                st.subheader("Назначение программной системы")

                st.markdown(
                    """
                    Программная система предназначена для выбора и анализа локаций
                    пунктов выдачи заказов на территории Москвы.

                    Система оформляет исследовательский GIS-пайплайн в виде
                    воспроизводимой программной реализации: от подготовки
                    пространственных данных и построения модели спроса до запуска
                    моделей размещения, расчёта метрик и визуализации результатов.
                    """
                )

                col1, col2, col3 = st.columns(3)

                with col1:
                    st.markdown("#### Входные данные")
                    st.markdown(
                        """
                        - OpenStreetMap;
                        - административные границы Москвы;
                        - жилая застройка;
                        - параметры расчёта;
                        - число размещаемых ПВЗ.
                        """
                    )

                with col2:
                    st.markdown("#### Расчётные модули")
                    st.markdown(
                        """
                        - пешеходный граф;
                        - точки спроса;
                        - кандидатные локации;
                        - 4 модели размещения;
                        - городские и районные метрики.
                        """
                    )

                with col3:
                    st.markdown("#### Выходные данные")
                    st.markdown(
                        """
                        - выбранные локации;
                        - таблицы метрик;
                        - карты размещения;
                        - карты изменений;
                        - графики насыщения;
                        - сравнительные панели.
                        """
                    )

                st.subheader("Реализованные модели")

                for key, label in MODEL_LABELS.items():
                    st.markdown(f"**{label}.** {MODEL_DESCRIPTIONS[key]}")

            with tab_model:
                st.subheader(MODEL_LABELS[model_name])
                st.write(MODEL_DESCRIPTIONS[model_name])

                df, file_path, error = load_model_safe(config, model_name)

                if error:
                    st.error(error)
                else:
                    st.markdown("#### Используемый CSV")
                    st.code(str(file_path.relative_to(config.root_dir)))

                    summary = model_summary(df, model_name)

                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Точек в конфигурации", summary["points"])
                    c2.metric(
                        "Уникальных районов",
                        summary["unique_districts"] if summary["unique_districts"] is not None else "—",
                    )
                    c3.metric("Точек в Зеленограде", summary["zelenograd_points"])
                    c4.metric("Заданное K", int(k))

                    if summary["source_counts"]:
                        st.markdown("#### Источник точек в модели")
                        st.json(summary["source_counts"])

                    st.markdown("#### Карта выбранных локаций")
                    render_single_map(df)

                    st.markdown("#### Таблица выбранных локаций")
                    st.dataframe(df, use_container_width=True)

                    st.markdown("#### Числовая сводка по CSV")
                    num_summary = summarize_result_table(df)

                    if num_summary.empty:
                        st.info("В таблице нет числовых колонок для сводки.")
                    else:
                        st.dataframe(num_summary, use_container_width=True)

            with tab_compare:
                st.subheader("Сравнение четырёх конфигураций сети")

                combined_df = build_combined_models_df(config)

                if combined_df.empty:
                    st.warning("Не удалось собрать общую таблицу моделей.")
                else:
                    st.markdown("#### Общая карта моделей")
                    render_combined_map(combined_df)

                    st.markdown("#### Легенда")
                    legend_cols = st.columns(len(MODEL_LABELS))

                    for col, (key, label) in zip(legend_cols, MODEL_LABELS.items()):
                        with col:
                            color = MODEL_COLORS[key]
                            st.markdown(
                                f"""
                                <div style="
                                    border-radius: 8px;
                                    padding: 8px;
                                    border: 1px solid #ddd;
                                    margin-bottom: 4px;">
                                    <div style="
                                        width: 18px;
                                        height: 18px;
                                        border-radius: 50%;
                                        background: rgba({color[0]}, {color[1]}, {color[2]}, 0.8);
                                        display: inline-block;
                                        margin-right: 8px;">
                                    </div>
                                    <b>{label}</b>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )

                    st.markdown("#### Сводка по моделям")

                    rows = []
                    for key in MODEL_LABELS:
                        df, _, error = load_model_safe(config, key)
                        if df is not None:
                            rows.append(model_summary(df, key))

                    summary_df = pd.DataFrame(rows)
                    display_df = summary_df.drop(columns=["source_counts"], errors="ignore")
                    st.dataframe(display_df, use_container_width=True)

                    if "district_name" in combined_df.columns:
                        st.markdown("#### Распределение выбранных точек по районам")

                        district_counts = (
                            combined_df
                            .groupby(["model_label", "district_name"])
                            .size()
                            .reset_index(name="points")
                            .sort_values(["model_label", "points"], ascending=[True, False])
                        )

                        st.dataframe(district_counts, use_container_width=True)

                    st.markdown("#### Объединённая таблица всех выбранных точек")
                    st.dataframe(combined_df, use_container_width=True)

                    csv = combined_df.to_csv(index=False).encode("utf-8-sig")
                    st.download_button(
                        label="Скачать объединённую таблицу CSV",
                        data=csv,
                        file_name="pvz_models_comparison.csv",
                        mime="text/csv",
                    )

            with tab_artifacts:
                st.subheader("Итоговые артефакты исследования")

                files = list_artifact_files(config.artifacts_dir)

                if not files:
                    st.warning(
                        "В папке артефактов не найдены изображения, таблицы или документы."
                    )
                    st.code(str(config.artifacts_dir))
                else:
                    st.write(f"Найдено файлов: {len(files)}")

                    selected = st.selectbox(
                        "Выберите артефакт",
                        options=files,
                        format_func=lambda p: str(p.relative_to(config.root_dir)),
                    )

                    st.code(str(selected.relative_to(config.root_dir)))
                    render_artifact_preview(selected)

                    with st.expander("Все найденные артефакты"):
                        for file in files:
                            st.write(file.relative_to(config.root_dir))

            with tab_pipeline:
                st.subheader("Расчётный pipeline проекта")

                st.markdown(
                    """
                    Полный расчётный режим представлен последовательностью Python-скриптов
                    в папке `scripts/final`. Они выполняют подготовку данных, построение
                    графа, формирование спроса, запуск моделей размещения и сборку
                    итоговых визуализаций.

                    В демонстрационном режиме используются уже рассчитанные результаты,
                    чтобы на защите не запускать длительные георасчёты заново.
                    """
                )

                if not config.scripts_dir.exists():
                    st.warning("Папка финальных скриптов не найдена.")
                    st.code(str(config.scripts_dir))
                else:
                    scripts = sorted(config.scripts_dir.glob("*.py"))

                    if not scripts:
                        st.info("В папке финальных скриптов нет .py файлов.")
                    else:
                        pipeline_df = pd.DataFrame(
                            {
                                "№": list(range(1, len(scripts) + 1)),
                                "script": [s.name for s in scripts],
                                "path": [str(s.relative_to(config.root_dir)) for s in scripts],
                            }
                        )

                        st.dataframe(pipeline_df, use_container_width=True)

                        st.markdown("#### Команды запуска")
                        st.code(
                            "\n".join(
                                f"python {s.relative_to(config.root_dir)}"
                                for s in scripts
                            )
                        )
        '''
    )

    write_file(
        "pvz_system/cli.py",
        r'''
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
        '''
    )

    print()
    print("=== Готово ===")
    print("Теперь выполни:")
    print("  python main.py compare-models")
    print("  python main.py list-artifacts")
    print("  python main.py list-scripts")
    print("  streamlit run app.py")


if __name__ == "__main__":
    main()