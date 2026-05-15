from pathlib import Path
import textwrap


def write_file(path: str, content: str) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
    print(f"[ok] создан/обновлён файл: {path}")


def main() -> None:
    write_file(
        "pvz_system/pipeline_runner.py",
        r'''
        from __future__ import annotations

        from dataclasses import dataclass
        from pathlib import Path
        import json
        import os
        import subprocess
        import sys
        import time


        @dataclass
        class PipelineStep:
            name: str
            script: Path
            enabled: bool = True


        @dataclass
        class PipelineResult:
            step_name: str
            script: str
            return_code: int
            duration_sec: float
            stdout: str
            stderr: str


        DEFAULT_PIPELINE_SCRIPTS = [
            "00_build_walk_graph_from_pbf.py",
            "01_district_features_from_osm.py",
            "02b_add_walk_metrics_multipoint.py",
            "05_make_demand_and_candidates_v2.py",
            "06_select_pvz_greedy_maxcoverage.py",
            "16_select_pvz_min_mean_time_k20.py",
            "18_select_pvz_max_effective_demand_k20.py",
            "20_select_effective_k20_keep_zelenogra.py",
            "21_compare_k20_four_networks_by_distri.py",
            "22_make_k20_conclusion_tables.py",
            "23_make_k20_final_panels.py",
        ]


        def save_runtime_config(
            root_dir: Path,
            input_pbf: Path,
            output_dir: Path,
            scripts_dir: Path,
            k: int,
        ) -> Path:
            """
            Сохраняет конфигурацию конкретного запуска.

            Дальше старые скрипты можно постепенно перевести на чтение этого файла.
            """
            config_dir = root_dir / "configs"
            config_dir.mkdir(parents=True, exist_ok=True)

            runtime_config_path = config_dir / "runtime_pipeline.json"

            data = {
                "input_pbf": str(input_pbf),
                "output_dir": str(output_dir),
                "scripts_dir": str(scripts_dir),
                "k": int(k),
                "created_by": "PVZ Streamlit Pipeline Runner",
            }

            runtime_config_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            return runtime_config_path


        def discover_pipeline_steps(scripts_dir: Path) -> list[PipelineStep]:
            """
            Ищет стандартные скрипты pipeline в scripts/final.
            Если стандартный скрипт не найден, он пропускается.
            """
            steps: list[PipelineStep] = []

            for script_name in DEFAULT_PIPELINE_SCRIPTS:
                script_path = scripts_dir / script_name
                if script_path.exists():
                    steps.append(
                        PipelineStep(
                            name=script_name,
                            script=script_path,
                            enabled=True,
                        )
                    )

            return steps


        def run_step(
            root_dir: Path,
            step: PipelineStep,
            runtime_config_path: Path,
            input_pbf: Path,
            output_dir: Path,
            extra_env: dict | None = None,
        ) -> PipelineResult:
            """
            Запускает один Python-скрипт как подпроцесс.

            В переменные окружения передаются пути:
            - PVZ_RUNTIME_CONFIG
            - PVZ_INPUT_PBF
            - PVZ_OUTPUT_DIR

            Чтобы старые скрипты реально использовали выбранный файл,
            их нужно научить читать эти переменные или runtime_pipeline.json.
            """
            env = os.environ.copy()

            env["PVZ_RUNTIME_CONFIG"] = str(runtime_config_path)
            env["PVZ_INPUT_PBF"] = str(input_pbf)
            env["PVZ_OUTPUT_DIR"] = str(output_dir)

            if extra_env:
                env.update(extra_env)

            start = time.time()

            process = subprocess.run(
                [sys.executable, str(step.script)],
                cwd=str(root_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )

            duration = time.time() - start

            return PipelineResult(
                step_name=step.name,
                script=str(step.script),
                return_code=process.returncode,
                duration_sec=duration,
                stdout=process.stdout,
                stderr=process.stderr,
            )


        def run_pipeline(
            root_dir: Path,
            input_pbf: Path,
            output_dir: Path,
            scripts_dir: Path,
            selected_script_names: list[str],
            k: int = 20,
        ):
            """
            Генератор результатов pipeline.
            После каждого шага отдаёт PipelineResult.
            """
            output_dir.mkdir(parents=True, exist_ok=True)

            runtime_config_path = save_runtime_config(
                root_dir=root_dir,
                input_pbf=input_pbf,
                output_dir=output_dir,
                scripts_dir=scripts_dir,
                k=k,
            )

            steps = discover_pipeline_steps(scripts_dir)
            selected = set(selected_script_names)

            for step in steps:
                if step.name not in selected:
                    continue

                yield run_step(
                    root_dir=root_dir,
                    step=step,
                    runtime_config_path=runtime_config_path,
                    input_pbf=input_pbf,
                    output_dir=output_dir,
                )
        '''
    )

    write_file(
        "pvz_system/runtime_paths.py",
        r'''
        from pathlib import Path
        import json
        import os


        def get_runtime_config_path() -> Path:
            """
            Возвращает путь к runtime-конфигу.
            Используется внутри старых расчётных скриптов после их адаптации.
            """
            env_path = os.getenv("PVZ_RUNTIME_CONFIG")

            if env_path:
                return Path(env_path)

            return Path("configs/runtime_pipeline.json")


        def load_runtime_config() -> dict:
            path = get_runtime_config_path()

            if not path.exists():
                return {}

            return json.loads(path.read_text(encoding="utf-8"))


        def get_input_pbf(default: str | None = None) -> Path | None:
            """
            Универсальный способ получить путь к входному .osm.pbf.

            Приоритет:
            1. переменная окружения PVZ_INPUT_PBF;
            2. configs/runtime_pipeline.json;
            3. default.
            """
            env_value = os.getenv("PVZ_INPUT_PBF")

            if env_value:
                return Path(env_value)

            config = load_runtime_config()

            if config.get("input_pbf"):
                return Path(config["input_pbf"])

            if default:
                return Path(default)

            return None


        def get_output_dir(default: str = "outputs") -> Path:
            """
            Универсальный способ получить папку выходных результатов.
            """
            env_value = os.getenv("PVZ_OUTPUT_DIR")

            if env_value:
                return Path(env_value)

            config = load_runtime_config()

            if config.get("output_dir"):
                return Path(config["output_dir"])

            return Path(default)


        def get_k(default: int = 20) -> int:
            config = load_runtime_config()

            try:
                return int(config.get("k", default))
            except Exception:
                return default
        '''
    )

    write_file(
        "pages/01_Полный_расчёт_pipeline.py",
        r'''
        from pathlib import Path
        import shutil
        import time

        import pandas as pd
        import streamlit as st

        from pvz_system.config import load_config
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


        config = load_config()
        root_dir = config.root_dir

        st.title("⚙️ Полный расчёт GIS-pipeline")
        st.caption(
            "Страница для запуска полного вычислительного pipeline: "
            "от входного .osm.pbf-файла до расчёта моделей и итоговых артефактов."
        )

        st.warning(
            "Важно: если старые скрипты содержат жёстко прописанные пути, "
            "они будут запускаться, но не обязательно используют выбранный здесь файл. "
            "Для полноценной работы их нужно постепенно перевести на чтение "
            "configs/runtime_pipeline.json или переменных окружения PVZ_INPUT_PBF / PVZ_OUTPUT_DIR."
        )

        tab_input, tab_steps, tab_run, tab_help = st.tabs(
            [
                "1. Входные данные",
                "2. Этапы pipeline",
                "3. Запуск",
                "4. Как адаптировать скрипты",
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
                value=str(root_dir / "outputs" / "pipeline_run"),
            )

            output_dir = Path(output_dir_value)
            if not output_dir.is_absolute():
                output_dir = root_dir / output_dir

            scripts_dir_value = st.text_input(
                "Папка финальных скриптов",
                value=str(config.scripts_dir),
            )

            scripts_dir = Path(scripts_dir_value)
            if not scripts_dir.is_absolute():
                scripts_dir = root_dir / scripts_dir

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
                ]
            )

            st.dataframe(checks, use_container_width=True)

            if not input_pbf.exists():
                st.error("Входной .osm.pbf-файл не найден.")

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
                При запуске будет создан файл `configs/runtime_pipeline.json`.
                В него записываются выбранный `.osm.pbf`, папка результатов,
                папка скриптов и параметр `K`.

                Скрипты также получают эти значения через переменные окружения:

                - `PVZ_RUNTIME_CONFIG`;
                - `PVZ_INPUT_PBF`;
                - `PVZ_OUTPUT_DIR`.
                """
            )

            start_button = st.button(
                "🚀 Запустить выбранные этапы",
                type="primary",
                use_container_width=True,
                disabled=not input_pbf.exists() or not scripts_dir.exists() or not selected_scripts,
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
                        st.error(
                            f"Pipeline остановлен на этапе: {result.step_name}"
                        )
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
            st.subheader("Как сделать старые скрипты настоящими этапами программы")

            st.markdown(
                """
                Сейчас эта страница уже умеет запускать скрипты как единый pipeline.
                Но чтобы выбранный в интерфейсе `.osm.pbf` реально использовался
                внутри расчётов, нужно заменить жёстко прописанные пути в старых
                скриптах на чтение runtime-конфига.

                В каждом расчётном скрипте можно добавить:

                ```python
                from pvz_system.runtime_paths import get_input_pbf, get_output_dir, get_k

                input_pbf = get_input_pbf("data/raw/moscow.osm.pbf")
                output_dir = get_output_dir("outputs")
                k = get_k(20)
                ```

                После этого скрипт будет брать входной файл и выходную папку
                из страницы Streamlit.
                """
            )

            st.markdown(
                """
                **Правильная логика итоговой программы:**

                1. пользователь задаёт `.osm.pbf`;
                2. приложение сохраняет runtime-конфиг;
                3. каждый этап pipeline читает этот конфиг;
                4. результаты складываются в выбранную папку;
                5. вкладки с результатами показывают новые CSV, карты и таблицы.
                """
            )
        '''
    )

    print()
    print("=== Готово ===")
    print("Запусти приложение:")
    print("  streamlit run app.py")
    print()
    print("В левом меню Streamlit появится отдельная страница:")
    print("  Полный расчёт pipeline")


if __name__ == "__main__":
    main()