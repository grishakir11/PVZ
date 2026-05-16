from pathlib import Path
import textwrap


ROOT = Path.cwd()


def write_file(path: str, content: str) -> None:
    file_path = ROOT / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
    print(f"[ok] записан файл: {path}")


def main() -> None:
    print("=== PVZ System Upgrade v3 ===")

    write_file(
        "pvz_system/reporting.py",
        r'''
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
        '''
    )

    write_file(
        "pvz_system/interface/dashboard_pro.py",
        r'''
        import pandas as pd
        import streamlit as st

        try:
            import pydeck as pdk
        except Exception:
            pdk = None

        try:
            import plotly.express as px
        except Exception:
            px = None

        from pvz_system.config import load_config
        from pvz_system.data_io import read_model_dataframe, find_model_file, detect_coordinate_columns
        from pvz_system.evaluation.metrics import summarize_result_table
        from pvz_system.reporting import (
            MODEL_LABELS,
            MODEL_DESCRIPTIONS,
            build_model_summary,
            build_combined_points,
            build_overlap_matrix,
            build_district_distribution,
            list_artifacts,
            list_scripts,
            make_markdown_report,
        )


        MODEL_COLORS = {
            "Максимизация охвата": [220, 80, 80, 180],
            "Минимизация среднего времени": [80, 140, 230, 180],
            "Максимизация эффективного спроса": [80, 180, 120, 180],
            "Ограниченная компромиссная модель": [180, 110, 220, 180],
        }


        def load_selected_model(config, model_name: str) -> tuple[pd.DataFrame | None, str | None]:
            file_path = find_model_file(config, model_name)

            if file_path is None:
                return None, None

            df = read_model_dataframe(config, model_name)

            if "sel_rank" in df.columns:
                df = df.sort_values("sel_rank").reset_index(drop=True)

            return df, str(file_path.relative_to(config.root_dir))


        def render_points_map(df: pd.DataFrame, label: str = "") -> None:
            lat_col, lon_col = detect_coordinate_columns(df)

            if not lat_col or not lon_col:
                st.info("Координатные колонки не найдены.")
                return

            map_df = df[[lat_col, lon_col]].dropna().copy()
            map_df = map_df.rename(columns={lat_col: "lat", lon_col: "lon"})

            if "district_name" in df.columns:
                map_df["district_name"] = df["district_name"]

            if "sel_rank" in df.columns:
                map_df["sel_rank"] = df["sel_rank"]

            if map_df.empty:
                st.info("Нет координат для отображения.")
                return

            if pdk is None:
                st.map(map_df, latitude="lat", longitude="lon")
                return

            tooltip = {
                "html": (
                    f"<b>{label}</b><br/>"
                    "Район: {district_name}<br/>"
                    "Ранг: {sel_rank}"
                ),
                "style": {"backgroundColor": "white", "color": "black"},
            }

            layer = pdk.Layer(
                "ScatterplotLayer",
                data=map_df,
                get_position="[lon, lat]",
                get_radius=450,
                get_fill_color=[220, 80, 80, 180],
                pickable=True,
                auto_highlight=True,
            )

            deck = pdk.Deck(
                map_style=None,
                initial_view_state=pdk.ViewState(
                    latitude=float(map_df["lat"].mean()),
                    longitude=float(map_df["lon"].mean()),
                    zoom=9,
                    pitch=0,
                ),
                layers=[layer],
                tooltip=tooltip,
            )

            st.pydeck_chart(deck, use_container_width=True)


        def render_combined_map(combined: pd.DataFrame) -> None:
            if combined.empty:
                st.warning("Нет данных для общей карты.")
                return

            combined = combined.copy()
            combined["color"] = combined["model_label"].map(MODEL_COLORS)

            if pdk is None:
                st.map(combined, latitude="lat", longitude="lon")
                return

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
                data=combined,
                get_position="[lon, lat]",
                get_fill_color="color",
                get_radius=350,
                pickable=True,
                auto_highlight=True,
            )

            deck = pdk.Deck(
                map_style=None,
                initial_view_state=pdk.ViewState(
                    latitude=float(combined["lat"].mean()),
                    longitude=float(combined["lon"].mean()),
                    zoom=9,
                    pitch=0,
                ),
                layers=[layer],
                tooltip=tooltip,
            )

            st.pydeck_chart(deck, use_container_width=True)


        def render_artifact(path) -> None:
            suffix = path.suffix.lower()

            if suffix in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
                st.image(str(path), use_container_width=True)
            elif suffix == ".csv":
                try:
                    df = pd.read_csv(path)
                    st.dataframe(df, use_container_width=True)
                except Exception as exc:
                    st.error(f"Не удалось прочитать CSV: {exc}")
            elif suffix == ".html":
                st.info("HTML-артефакт найден. Откройте его отдельно из папки проекта.")
                st.code(str(path))
            else:
                st.info("Предпросмотр для этого типа файла не реализован.")
                st.code(str(path))


        def run_dashboard() -> None:
            st.set_page_config(
                page_title="PVZ Location System",
                page_icon="📍",
                layout="wide",
            )

            config = load_config()

            st.title("📍 PVZ Location System")
            st.caption(
                "Программная система выбора и анализа локаций пунктов выдачи заказов в Москве"
            )

            with st.sidebar:
                st.header("Управление")

                selected_model = st.selectbox(
                    "Модель размещения",
                    options=list(MODEL_LABELS.keys()),
                    format_func=lambda key: MODEL_LABELS[key],
                )

                st.divider()

                st.markdown("**Пути проекта**")
                st.caption("Модели")
                st.code(str(config.models_dir))
                st.caption("Артефакты")
                st.code(str(config.artifacts_dir))
                st.caption("Скрипты")
                st.code(str(config.scripts_dir))

            summary = build_model_summary(config)
            combined = build_combined_points(config)
            artifacts = list_artifacts(config)
            scripts = list_scripts(config)

            tab_overview, tab_model, tab_compare, tab_artifacts, tab_report, tab_demo = st.tabs(
                [
                    "Обзор",
                    "Модель",
                    "Сравнение",
                    "Артефакты",
                    "Отчёт",
                    "Демонстрация",
                ]
            )

            with tab_overview:
                st.subheader("Обзор программной реализации")

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Моделей", len(MODEL_LABELS))
                c2.metric("Выбранных точек во всех моделях", len(combined))
                c3.metric("Финальных скриптов", len(scripts))
                c4.metric("Артефактов", len(artifacts))

                st.markdown(
                    """
                    Проект оформлен как воспроизводимый GIS-пайплайн и демонстрационная
                    программная система. Исследовательская часть отвечает за подготовку
                    пространственных данных и расчёт моделей, а интерфейс позволяет
                    быстро показать результаты комиссии без повторного запуска тяжёлых
                    георасчётов.
                    """
                )

                st.markdown("### Архитектура")

                col1, col2, col3 = st.columns(3)

                with col1:
                    st.markdown(
                        """
                        **Входные данные**

                        - OpenStreetMap;
                        - жилая застройка;
                        - административные границы;
                        - параметры модели;
                        - число размещаемых ПВЗ.
                        """
                    )

                with col2:
                    st.markdown(
                        """
                        **Расчётные блоки**

                        - пешеходный граф;
                        - модель спроса;
                        - кандидатные локации;
                        - оптимизационные модели;
                        - городские и районные метрики.
                        """
                    )

                with col3:
                    st.markdown(
                        """
                        **Выходные данные**

                        - CSV выбранных локаций;
                        - карты размещения;
                        - сравнительные графики;
                        - районные таблицы;
                        - итоговые панели.
                        """
                    )

                st.markdown("### Реализованные модели")

                for key, label in MODEL_LABELS.items():
                    st.markdown(f"**{label}.** {MODEL_DESCRIPTIONS[key]}")

                st.markdown("### Сводка по моделям")
                st.dataframe(summary, use_container_width=True)

            with tab_model:
                label = MODEL_LABELS[selected_model]
                st.subheader(label)
                st.write(MODEL_DESCRIPTIONS[selected_model])

                df, source_file = load_selected_model(config, selected_model)

                if df is None:
                    st.error("Файл модели не найден.")
                else:
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Точек в модели", len(df))

                    if "district_name" in df.columns:
                        c2.metric("Уникальных районов", df["district_name"].nunique())
                    else:
                        c2.metric("Уникальных районов", "—")

                    if "source" in df.columns:
                        fixed_count = int(df["source"].astype(str).str.contains("fixed", case=False).sum())
                        c3.metric("Фиксированных точек", fixed_count)
                    else:
                        c3.metric("Фиксированных точек", "—")

                    st.markdown("**Файл результата**")
                    st.code(source_file)

                    st.markdown("### Карта выбранных локаций")
                    render_points_map(df, label)

                    st.markdown("### Таблица выбранных точек")
                    st.dataframe(df, use_container_width=True)

                    if "district_name" in df.columns:
                        st.markdown("### Распределение по районам")

                        district_counts = (
                            df["district_name"]
                            .value_counts()
                            .reset_index()
                        )
                        district_counts.columns = ["district_name", "points"]

                        if px is not None:
                            fig = px.bar(
                                district_counts,
                                x="district_name",
                                y="points",
                                title="Количество выбранных точек по районам",
                            )
                            st.plotly_chart(fig, use_container_width=True)
                        else:
                            st.bar_chart(district_counts.set_index("district_name"))

                    st.markdown("### Числовая сводка")
                    numeric_summary = summarize_result_table(df)

                    if numeric_summary.empty:
                        st.info("Нет числовых колонок для сводки.")
                    else:
                        st.dataframe(numeric_summary, use_container_width=True)

            with tab_compare:
                st.subheader("Сравнение моделей размещения")

                st.markdown(
                    """
                    Этот раздел показывает, что разные критерии оптимизации выбирают
                    разные пространственные конфигурации сети. Это важный результат
                    работы: универсально лучшей модели нет, выбор зависит от цели.
                    """
                )

                st.markdown("### Общая карта четырёх моделей")
                render_combined_map(combined)

                st.markdown("### Сводная таблица")
                st.dataframe(summary, use_container_width=True)

                if px is not None and not summary.empty:
                    st.markdown("### Сравнение по числу районов")

                    fig = px.bar(
                        summary,
                        x="model_label",
                        y="unique_districts",
                        title="Количество уникальных районов в выбранной конфигурации",
                    )
                    st.plotly_chart(fig, use_container_width=True)

                    st.markdown("### Точки в Зеленограде")

                    fig2 = px.bar(
                        summary,
                        x="model_label",
                        y="zelenograd_points",
                        title="Количество выбранных точек в Зеленоградском кластере",
                    )
                    st.plotly_chart(fig2, use_container_width=True)

                st.markdown("### Пересечение выбранных локаций")

                overlap = build_overlap_matrix(config)
                st.dataframe(overlap, use_container_width=True)

                st.caption(
                    "Пересечение считается по координатам с округлением. "
                    "Это позволяет увидеть, насколько разные модели выбирают похожие точки."
                )

                district_distribution = build_district_distribution(config)

                if not district_distribution.empty:
                    st.markdown("### Распределение по районам")
                    st.dataframe(district_distribution, use_container_width=True)

                st.markdown("### Объединённая таблица всех точек")
                st.dataframe(combined, use_container_width=True)

                csv = combined.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    "Скачать объединённую таблицу CSV",
                    data=csv,
                    file_name="pvz_all_models_points.csv",
                    mime="text/csv",
                )

            with tab_artifacts:
                st.subheader("Итоговые артефакты исследования")

                if not artifacts:
                    st.warning("Артефакты не найдены.")
                    st.code(str(config.artifacts_dir))
                else:
                    st.write(f"Найдено файлов: {len(artifacts)}")

                    selected_artifact = st.selectbox(
                        "Выберите файл",
                        options=artifacts,
                        format_func=lambda p: str(p.relative_to(config.root_dir)),
                    )

                    st.code(str(selected_artifact.relative_to(config.root_dir)))
                    render_artifact(selected_artifact)

                    with st.expander("Список всех артефактов"):
                        for path in artifacts:
                            st.write(path.relative_to(config.root_dir))

            with tab_report:
                st.subheader("Автоматический отчёт по программной системе")

                report_text = make_markdown_report(config)

                st.download_button(
                    "Скачать отчёт Markdown",
                    data=report_text.encode("utf-8"),
                    file_name="pvz_system_report.md",
                    mime="text/markdown",
                )

                st.markdown(report_text)

            with tab_demo:
                st.subheader("Сценарий демонстрации на защите")

                st.markdown(
                    """
                    **1. Назначение системы.**  
                    Показать вкладку «Обзор» и объяснить, что проект реализован
                    как воспроизводимый GIS-пайплайн и демонстрационная система.

                    **2. Входные данные и архитектура.**  
                    Кратко объяснить, что используются OpenStreetMap, жилая застройка,
                    пешеходный граф, точки спроса и кандидатные локации.

                    **3. Модели размещения.**  
                    Перейти во вкладку «Модель» и показать четыре варианта:
                    максимизация охвата, минимизация среднего времени,
                    максимизация эффективного спроса и компромиссная модель.

                    **4. Карта выбранной модели.**  
                    Показать карту и таблицу выбранных точек. Объяснить, что каждая
                    точка имеет координаты, район и ранг выбора.

                    **5. Сравнение моделей.**  
                    Перейти во вкладку «Сравнение» и показать, что модели выбирают
                    разные пространственные конфигурации.

                    **6. Артефакты исследования.**  
                    Открыть вкладку «Артефакты» и показать итоговые карты, графики
                    или таблицы, сформированные расчётным pipeline.

                    **7. Вывод.**  
                    Подчеркнуть, что программная реализация позволяет не только
                    получить одну карту, но и сравнить разные стратегии размещения
                    ПВЗ по единой системе показателей.
                    """
                )
        '''
    )

    write_file(
        "app.py",
        r'''
        from pvz_system.interface.dashboard_pro import run_dashboard


        if __name__ == "__main__":
            run_dashboard()
        '''
    )

    write_file(
        "make_demo_report.py",
        r'''
        from pathlib import Path

        from pvz_system.config import load_config
        from pvz_system.reporting import make_markdown_report


        def main() -> None:
            config = load_config()
            config.outputs_dir.mkdir(parents=True, exist_ok=True)

            report = make_markdown_report(config)
            output_path = config.outputs_dir / "pvz_system_report.md"

            output_path.write_text(report, encoding="utf-8")

            print(f"Отчёт сохранён: {output_path}")


        if __name__ == "__main__":
            main()
        '''
    )

    write_file(
        "docs/DEMO_SCENARIO.md",
        r'''
        # Сценарий демонстрации программной реализации

        ## 1. Вступление

        В рамках работы была разработана программная система для выбора и анализа
        локаций пунктов выдачи заказов на территории Москвы. Система оформляет
        исследовательский GIS-пайплайн в удобный для демонстрации и повторного
        использования вид.

        ## 2. Что показать первым

        Открыть демонстрационный интерфейс:

        ```bash
        streamlit run app.py
        ```

        На вкладке «Обзор» показать:

        - назначение системы;
        - входные данные;
        - расчётные блоки;
        - выходные артефакты;
        - четыре реализованные модели.

        ## 3. Показ выбранной модели

        Перейти на вкладку «Модель».

        Показать:

        - выбор модели в боковом меню;
        - описание модели;
        - CSV-файл результата;
        - карту выбранных локаций;
        - таблицу выбранных точек;
        - распределение по районам.

        ## 4. Сравнение моделей

        Перейти на вкладку «Сравнение».

        Показать:

        - общую карту четырёх моделей;
        - сводную таблицу;
        - пересечение выбранных локаций;
        - распределение выбранных точек по районам.

        Основной комментарий:

        > Разные критерии оптимизации приводят к различным пространственным
        > конфигурациям сети, поэтому итоговый выбор модели зависит от управленческой цели.

        ## 5. Артефакты

        Перейти на вкладку «Артефакты».

        Показать итоговые карты, таблицы и графики, сформированные расчётным pipeline.

        ## 6. Финальный вывод

        Программная реализация позволяет:

        - воспроизводимо готовить пространственные данные;
        - рассчитывать несколько моделей размещения;
        - сравнивать конфигурации сети по единой системе показателей;
        - анализировать результат по городу и районам;
        - использовать результаты для предварительного отбора зон размещения ПВЗ.
        '''
    )

    write_file(
        "docs/PROGRAM_IMPLEMENTATION_TEXT.md",
        r'''
        # Текст для раздела о программной реализации

        В рамках выпускной квалификационной работы была разработана программная
        система для выбора и анализа локаций пунктов выдачи заказов на территории
        Москвы. Система реализует воспроизводимый GIS-пайплайн, охватывающий полный
        цикл обработки данных: подготовку открытых пространственных данных,
        построение пешеходного графа, формирование модели потенциального спроса,
        генерацию кандидатных локаций, запуск моделей оптимизационного размещения,
        расчёт показателей качества сети и визуализацию результатов.

        Программная реализация выполнена на языке Python. Для работы с табличными
        и пространственными данными используются библиотеки Pandas, GeoPandas,
        Shapely, OSMnx и Pyrosm. Для графовых расчётов применяется NetworkX.
        Визуализация результатов выполняется средствами Matplotlib, Plotly,
        PyDeck и Streamlit.

        Архитектурно система разделена на несколько функциональных блоков. Блок
        подготовки данных отвечает за извлечение и предварительную обработку
        пространственных слоёв. Блок построения графа формирует пешеходную сеть
        города и обеспечивает расчёт времени доступа. Блок моделирования спроса
        формирует точки потенциального спроса на основе жилой застройки. Блок
        оптимизации реализует несколько моделей размещения ПВЗ: максимизацию
        охвата, минимизацию среднего времени доступа, максимизацию эффективного
        спроса и ограниченную компромиссную модель. Блок оценки рассчитывает
        городские и районные метрики, а блок визуализации формирует карты,
        графики и сравнительные панели.

        Для демонстрации работы системы был реализован интерактивный интерфейс.
        Он позволяет выбрать модель размещения, просмотреть рассчитанную
        конфигурацию сети, отобразить выбранные точки на карте, сравнить модели
        между собой, открыть итоговые артефакты исследования и сформировать
        краткий отчёт. Такой формат позволяет показать программную реализацию
        не как набор отдельных скриптов, а как целостную систему поддержки
        принятия решений.

        Система поддерживает два режима работы. Исследовательский режим
        предназначен для полного запуска расчётного pipeline и формирования
        промежуточных данных. Демонстрационный режим использует заранее
        рассчитанные результаты, что позволяет быстро и надёжно показать работу
        программы на защите без повторного запуска длительных георасчётов.
        '''
    )

    print()
    print("=== Готово ===")
    print("Дальше выполни:")
    print("  python upgrade_pvz_system_v3.py")
    print("  python make_demo_report.py")
    print("  streamlit run app.py")


if __name__ == "__main__":
    main()