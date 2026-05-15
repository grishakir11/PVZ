from pathlib import Path
import textwrap


DASHBOARD_PATH = Path("pvz_system/interface/dashboard_pro.py")
APP_PATH = Path("app.py")


DASHBOARD_CODE = r'''
from dataclasses import replace
from pathlib import Path
import json

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
from pvz_system.data_io import (
    read_model_dataframe,
    find_model_file,
    detect_coordinate_columns,
)
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


def resolve_runtime_path(root_dir: Path, value: str) -> Path:
    value = str(value).strip()

    if not value:
        return root_dir

    path = Path(value).expanduser()

    if path.is_absolute():
        return path

    return root_dir / path


def config_path_value(root_dir: Path, value: str) -> str:
    path = resolve_runtime_path(root_dir, value)

    try:
        return str(path.relative_to(root_dir)).replace("\\", "/")
    except ValueError:
        return str(path)


def save_paths_to_config(base_config, config_file: Path) -> None:
    raw = json.loads(config_file.read_text(encoding="utf-8"))
    raw.setdefault("paths", {})

    raw["paths"]["models_dir"] = config_path_value(
        base_config.root_dir,
        st.session_state["models_dir_input"],
    )
    raw["paths"]["artifacts_dir"] = config_path_value(
        base_config.root_dir,
        st.session_state["artifacts_dir_input"],
    )
    raw["paths"]["scripts_dir"] = config_path_value(
        base_config.root_dir,
        st.session_state["scripts_dir_input"],
    )
    raw["paths"]["outputs_dir"] = config_path_value(
        base_config.root_dir,
        st.session_state["outputs_dir_input"],
    )

    config_file.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def init_sidebar_paths(config) -> None:
    if st.session_state.get("paths_initialized"):
        return

    st.session_state["models_dir_input"] = str(config.models_dir)
    st.session_state["artifacts_dir_input"] = str(config.artifacts_dir)
    st.session_state["scripts_dir_input"] = str(config.scripts_dir)
    st.session_state["outputs_dir_input"] = str(config.outputs_dir)
    st.session_state["paths_initialized"] = True


def apply_sidebar_paths(config):
    return replace(
        config,
        models_dir=resolve_runtime_path(
            config.root_dir,
            st.session_state["models_dir_input"],
        ),
        artifacts_dir=resolve_runtime_path(
            config.root_dir,
            st.session_state["artifacts_dir_input"],
        ),
        scripts_dir=resolve_runtime_path(
            config.root_dir,
            st.session_state["scripts_dir_input"],
        ),
        outputs_dir=resolve_runtime_path(
            config.root_dir,
            st.session_state["outputs_dir_input"],
        ),
    )


def path_status(path: Path) -> str:
    return "✅ найдена" if path.exists() else "❌ не найдена"


def load_selected_model(config, model_name: str):
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


def render_artifact(path: Path) -> None:
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
        st.info("HTML-артефакт найден. Его лучше открыть отдельно из папки проекта.")
        st.code(str(path))
    else:
        st.info("Предпросмотр для этого типа файла не реализован.")
        st.code(str(path))


def render_sidebar_paths(base_config):
    st.sidebar.header("Управление")

    selected_model = st.sidebar.selectbox(
        "Модель размещения",
        options=list(MODEL_LABELS.keys()),
        format_func=lambda key: MODEL_LABELS[key],
    )

    st.sidebar.divider()

    st.sidebar.subheader("Пути проекта")
    st.sidebar.caption("Можно указать абсолютный путь или путь относительно корня проекта.")

    st.sidebar.text_input(
        "Папка моделей",
        key="models_dir_input",
        help="Например: pvz_project/models",
    )

    st.sidebar.text_input(
        "Папка артефактов",
        key="artifacts_dir_input",
        help="Например: pvz_project/deliverables/thesis_artifacts",
    )

    st.sidebar.text_input(
        "Папка финальных скриптов",
        key="scripts_dir_input",
        help="Например: scripts/final",
    )

    st.sidebar.text_input(
        "Папка выходных файлов",
        key="outputs_dir_input",
        help="Например: outputs",
    )

    col1, col2 = st.sidebar.columns(2)

    with col1:
        if st.button("Применить", use_container_width=True):
            st.rerun()

    with col2:
        if st.button("Сохранить", use_container_width=True):
            try:
                save_paths_to_config(
                    base_config,
                    base_config.root_dir / "configs" / "moscow_demo.json",
                )
                st.sidebar.success("Сохранено")
            except Exception as exc:
                st.sidebar.error(str(exc))

    runtime_config = apply_sidebar_paths(base_config)

    st.sidebar.divider()
    st.sidebar.subheader("Проверка путей")

    st.sidebar.caption("Модели")
    st.sidebar.write(path_status(runtime_config.models_dir))

    st.sidebar.caption("Артефакты")
    st.sidebar.write(path_status(runtime_config.artifacts_dir))

    st.sidebar.caption("Скрипты")
    st.sidebar.write(path_status(runtime_config.scripts_dir))

    st.sidebar.caption("Выходные файлы")
    st.sidebar.write(path_status(runtime_config.outputs_dir))

    return selected_model, runtime_config


def run_dashboard() -> None:
    st.set_page_config(
        page_title="PVZ Location System",
        page_icon="📍",
        layout="wide",
    )

    base_config = load_config()
    init_sidebar_paths(base_config)

    selected_model, config = render_sidebar_paths(base_config)

    st.title("📍 PVZ Location System")
    st.caption(
        "Программная система выбора и анализа локаций пунктов выдачи заказов в Москве"
    )

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
            пространственных данных и расчёт моделей, а интерфейс позволяет быстро
            показать результаты комиссии без повторного запуска тяжёлых георасчётов.
            """
        )

        st.markdown("### Используемые пути")

        paths_df = pd.DataFrame(
            [
                {"раздел": "Модели", "путь": str(config.models_dir), "статус": path_status(config.models_dir)},
                {"раздел": "Артефакты", "путь": str(config.artifacts_dir), "статус": path_status(config.artifacts_dir)},
                {"раздел": "Скрипты", "путь": str(config.scripts_dir), "статус": path_status(config.scripts_dir)},
                {"раздел": "Выходные файлы", "путь": str(config.outputs_dir), "статус": path_status(config.outputs_dir)},
            ]
        )

        st.dataframe(paths_df, use_container_width=True)

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
            st.error("Файл модели не найден. Проверь путь к папке моделей слева.")
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

                district_counts = df["district_name"].value_counts().reset_index()
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
            st.warning("Артефакты не найдены. Проверь путь к папке артефактов слева.")
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


APP_CODE = r'''
from pvz_system.interface.dashboard_pro import run_dashboard


if __name__ == "__main__":
    run_dashboard()
'''


def main() -> None:
    DASHBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_PATH.write_text(
        textwrap.dedent(DASHBOARD_CODE).strip() + "\n",
        encoding="utf-8",
    )

    APP_PATH.write_text(
        textwrap.dedent(APP_CODE).strip() + "\n",
        encoding="utf-8",
    )

    print("[ok] dashboard_pro.py полностью перезаписан")
    print("[ok] app.py обновлён")
    print()
    print("Теперь ОБЯЗАТЕЛЬНО останови Streamlit через Ctrl+C и запусти заново:")
    print("  streamlit run app.py")


if __name__ == "__main__":
    main()