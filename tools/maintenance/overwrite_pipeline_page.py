from pathlib import Path
import textwrap


PAGE_PATH = Path("pages/01_Полный_расчёт_pipeline.py")


PAGE_CODE = r'''
from pathlib import Path
import shutil

import pandas as pd
import streamlit as st

from pvz_system.config import load_config
from pvz_system.ui_path_state import render_path_editor
from pvz_system.pipeline_runner import (
    discover_pipeline_steps,
    run_pipeline,
)


st.set_page_config(
    page_title="Полный расчёт pipeline",
    page_icon="⚙️",
    layout="wide",
)


def save_uploaded_pbf(uploaded_file, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / uploaded_file.name

    with target_path.open("wb") as f:
        shutil.copyfileobj(uploaded_file, f)

    return target_path


def status_badge(ok: bool) -> str:
    return "✅ успешно" if ok else "❌ ошибка"


base_config = load_config()

with st.sidebar:
    st.header("Настройки путей")
    config = render_path_editor(base_config, location="pipeline_sidebar")

root_dir = config.root_dir

st.title("⚙️ Полный расчёт GIS-pipeline")
st.caption(
    "Страница для запуска полного вычислительного pipeline: "
    "от входного .osm.pbf-файла до расчёта моделей и итоговых артефактов."
)

st.info(
    "На этой странице используется тот же набор путей, что и на основной странице приложения. "
    "Пути сохраняются в configs/ui_paths.json и не должны пропадать при переключении страниц."
)

tab_input, tab_steps, tab_run, tab_help = st.tabs(
    [
        "1. Входные данные",
        "2. Этапы pipeline",
        "3. Запуск",
        "4. Пояснение",
    ]
)

with tab_input:
    st.subheader("Входной файл геоданных")

    input_mode = st.radio(
        "Способ указания .osm.pbf",
        [
            "Указать путь к существующему файлу",
            "Загрузить файл через интерфейс",
        ],
        horizontal=True,
    )

    default_raw_dir = root_dir / "data" / "raw"
    default_raw_dir.mkdir(parents=True, exist_ok=True)

    if input_mode == "Указать путь к существующему файлу":
        input_pbf_value = st.text_input(
            "Путь к .osm.pbf",
            value=str(default_raw_dir / "moscow.osm.pbf"),
            help="Можно указать абсолютный путь или путь относительно корня проекта.",
        )

        input_pbf = Path(input_pbf_value)

        if not input_pbf.is_absolute():
            input_pbf = root_dir / input_pbf

    else:
        uploaded_file = st.file_uploader(
            "Загрузите .osm.pbf-файл",
            type=["pbf", "osm"],
        )

        if uploaded_file is not None:
            input_pbf = save_uploaded_pbf(uploaded_file, default_raw_dir)
            st.success(f"Файл сохранён: {input_pbf}")
        else:
            input_pbf = default_raw_dir / "moscow.osm.pbf"

    output_dir_value = st.text_input(
        "Папка выходных результатов",
        value=str(config.outputs_dir / "pipeline_run"),
    )

    output_dir = Path(output_dir_value)

    if not output_dir.is_absolute():
        output_dir = root_dir / output_dir

    scripts_dir = config.scripts_dir

    k = st.number_input(
        "Число размещаемых ПВЗ K",
        min_value=1,
        max_value=200,
        value=20,
        step=1,
    )

    st.markdown("### Проверка путей")

    checks = pd.DataFrame(
        [
            {
                "объект": "Входной .osm.pbf",
                "путь": str(input_pbf),
                "найден": input_pbf.exists(),
            },
            {
                "объект": "Папка выходных результатов",
                "путь": str(output_dir),
                "найден": output_dir.exists(),
            },
            {
                "объект": "Папка скриптов",
                "путь": str(scripts_dir),
                "найден": scripts_dir.exists(),
            },
            {
                "объект": "Папка моделей",
                "путь": str(config.models_dir),
                "найден": config.models_dir.exists(),
            },
            {
                "объект": "Папка артефактов",
                "путь": str(config.artifacts_dir),
                "найден": config.artifacts_dir.exists(),
            },
        ]
    )

    st.dataframe(checks, use_container_width=True)

    if not input_pbf.exists():
        st.warning("Входной .osm.pbf-файл пока не найден.")

    if not scripts_dir.exists():
        st.error("Папка со скриптами не найдена.")

with tab_steps:
    st.subheader("Этапы расчётного pipeline")

    steps = discover_pipeline_steps(scripts_dir)

    if not steps:
        st.error("Не найдено стандартных скриптов pipeline.")
        st.stop()

    st.write(f"Найдено этапов: {len(steps)}")

    selected_scripts = []

    for step in steps:
        checked = st.checkbox(
            step.name,
            value=True,
            help=str(step.script),
        )

        if checked:
            selected_scripts.append(step.name)

    st.markdown("### Выбранные этапы")
    st.write(selected_scripts)

with tab_run:
    st.subheader("Запуск расчёта")

    st.markdown(
        """
        При запуске создаётся файл `configs/runtime_pipeline.json`.
        В него записываются:

        - выбранный `.osm.pbf`;
        - папка выходных результатов;
        - папка скриптов;
        - параметр `K`.

        Также эти значения передаются скриптам через переменные окружения:

        - `PVZ_RUNTIME_CONFIG`;
        - `PVZ_INPUT_PBF`;
        - `PVZ_OUTPUT_DIR`.
        """
    )

    can_run = input_pbf.exists() and scripts_dir.exists() and bool(selected_scripts)

    start_button = st.button(
        "🚀 Запустить выбранные этапы",
        type="primary",
        use_container_width=True,
        disabled=not can_run,
    )

    if not can_run:
        st.warning(
            "Для запуска нужен существующий .osm.pbf-файл, найденная папка скриптов "
            "и хотя бы один выбранный этап."
        )

    if start_button:
        output_dir.mkdir(parents=True, exist_ok=True)

        status_box = st.empty()
        progress = st.progress(0)
        log_area = st.container()

        total = len(selected_scripts)
        results = []

        for idx, result in enumerate(
            run_pipeline(
                root_dir=root_dir,
                input_pbf=input_pbf,
                output_dir=output_dir,
                scripts_dir=scripts_dir,
                selected_script_names=selected_scripts,
                k=int(k),
            ),
            start=1,
        ):
            results.append(result)

            progress.progress(idx / total)
            status_box.info(
                f"Выполнен этап {idx}/{total}: {result.step_name} "
                f"({status_badge(result.return_code == 0)})"
            )

            with log_area.expander(
                f"{result.step_name} — {status_badge(result.return_code == 0)} — "
                f"{result.duration_sec:.1f} сек.",
                expanded=result.return_code != 0,
            ):
                st.markdown("**STDOUT**")
                st.code(result.stdout or "пусто")

                st.markdown("**STDERR**")
                st.code(result.stderr or "пусто")

            if result.return_code != 0:
                st.error(f"Pipeline остановлен на этапе: {result.step_name}")
                break

        st.markdown("### Итоги запуска")

        result_df = pd.DataFrame(
            [
                {
                    "step": r.step_name,
                    "script": r.script,
                    "return_code": r.return_code,
                    "duration_sec": round(r.duration_sec, 2),
                    "status": status_badge(r.return_code == 0),
                }
                for r in results
            ]
        )

        st.dataframe(result_df, use_container_width=True)

        runtime_config_path = root_dir / "configs" / "runtime_pipeline.json"

        if runtime_config_path.exists():
            st.markdown("### Runtime-конфиг запуска")
            st.code(runtime_config_path.read_text(encoding="utf-8"))

with tab_help:
    st.subheader("Пояснение по странице полного расчёта")

    st.markdown(
        """
        Эта страница нужна, чтобы приложение выглядело не только как просмотрщик
        готовых CSV, а как оболочка для запуска полного расчётного pipeline.

        Логика работы:

        1. пользователь указывает входной `.osm.pbf`;
        2. выбирает папку выходных результатов;
        3. выбирает этапы расчёта;
        4. приложение создаёт runtime-конфиг;
        5. выбранные скрипты запускаются последовательно;
        6. пользователь видит логи и статус каждого этапа.

        Общие пути приложения хранятся в `configs/ui_paths.json`, поэтому при
        переключении между основной страницей и страницей pipeline они не должны
        сбрасываться.
        """
    )
'''


def main() -> None:
    PAGE_PATH.parent.mkdir(parents=True, exist_ok=True)

    PAGE_PATH.write_text(
        textwrap.dedent(PAGE_CODE).strip() + "\n",
        encoding="utf-8",
    )

    print("[ok] Страница pipeline полностью перезаписана")
    print("Теперь останови Streamlit через Ctrl+C и запусти заново:")
    print("  streamlit run app.py")


if __name__ == "__main__":
    main()