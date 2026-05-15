from pathlib import Path
import re


DASHBOARD_PATH = Path("pvz_system/interface/dashboard_pro.py")


def main() -> None:
    if not DASHBOARD_PATH.exists():
        raise FileNotFoundError(f"Не найден файл: {DASHBOARD_PATH}")

    text = DASHBOARD_PATH.read_text(encoding="utf-8")

    # 1. Проверяем импорты
    if "from dataclasses import replace" not in text:
        text = text.replace(
            "import pandas as pd\n",
            "from dataclasses import replace\n"
            "from pathlib import Path\n"
            "import json\n\n"
            "import pandas as pd\n",
        )

    # 2. Добавляем helper-функции, если их ещё нет
    if "# === PATH CONFIG HELPERS ===" not in text:
        helpers = r'''
# === PATH CONFIG HELPERS ===

def resolve_runtime_path(root_dir: Path, value: str) -> Path:
    """
    Принимает абсолютный путь или путь относительно корня проекта.
    """
    value = value.strip()

    if not value:
        return root_dir

    path = Path(value).expanduser()

    if path.is_absolute():
        return path

    return root_dir / path


def make_path_for_config(root_dir: Path, path_value: str) -> str:
    """
    Сохраняет путь в конфиг.
    Если путь внутри проекта, сохраняет относительно корня.
    Иначе сохраняет абсолютный путь.
    """
    path = resolve_runtime_path(root_dir, path_value)

    try:
        return str(path.relative_to(root_dir)).replace("\\", "/")
    except ValueError:
        return str(path)


def save_runtime_paths_to_config(
    root_dir: Path,
    config_path: Path,
    models_dir: str,
    artifacts_dir: str,
    scripts_dir: str,
    outputs_dir: str,
) -> None:
    if not config_path.exists():
        raise FileNotFoundError(f"Не найден конфиг: {config_path}")

    raw = json.loads(config_path.read_text(encoding="utf-8"))

    raw.setdefault("paths", {})
    raw["paths"]["models_dir"] = make_path_for_config(root_dir, models_dir)
    raw["paths"]["artifacts_dir"] = make_path_for_config(root_dir, artifacts_dir)
    raw["paths"]["scripts_dir"] = make_path_for_config(root_dir, scripts_dir)
    raw["paths"]["outputs_dir"] = make_path_for_config(root_dir, outputs_dir)

    config_path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def init_path_state(config) -> None:
    """
    Инициализирует значения полей в sidebar один раз.
    """
    if st.session_state.get("pvz_paths_initialized"):
        return

    st.session_state["models_dir_input"] = str(config.models_dir)
    st.session_state["artifacts_dir_input"] = str(config.artifacts_dir)
    st.session_state["scripts_dir_input"] = str(config.scripts_dir)
    st.session_state["outputs_dir_input"] = str(config.outputs_dir)
    st.session_state["pvz_paths_initialized"] = True


def apply_runtime_paths(config):
    """
    Возвращает копию config с путями, заданными пользователем в интерфейсе.
    """
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

'''
        text = text.replace(
            "def run_dashboard() -> None:",
            helpers + "\n\ndef run_dashboard() -> None:",
        )

    # 3. Добавляем init_path_state после load_config
    text = re.sub(
        r"(\n\s+config = load_config\(\)\n)(?!\s+init_path_state\(config\))",
        r"\1            init_path_state(config)\n",
        text,
        count=1,
    )

    # 4. Заменяем блок путей в sidebar на редактируемый.
    # Ищем от заголовка "**Пути проекта**" до строки summary = build_model_summary(config)
    new_paths_block = r'''                st.markdown("**Пути проекта**")
                st.caption(
                    "Можно указать абсолютный путь или путь относительно корня проекта."
                )

                st.text_input(
                    "Папка моделей",
                    key="models_dir_input",
                    help="Например: pvz_project/models",
                )

                st.text_input(
                    "Папка артефактов",
                    key="artifacts_dir_input",
                    help="Например: pvz_project/deliverables/thesis_artifacts",
                )

                st.text_input(
                    "Папка финальных скриптов",
                    key="scripts_dir_input",
                    help="Например: scripts/final",
                )

                st.text_input(
                    "Папка выходных файлов",
                    key="outputs_dir_input",
                    help="Например: outputs",
                )

                col_apply, col_save = st.columns(2)

                with col_apply:
                    if st.button("Применить", use_container_width=True):
                        st.rerun()

                with col_save:
                    if st.button("Сохранить", use_container_width=True):
                        try:
                            save_runtime_paths_to_config(
                                root_dir=config.root_dir,
                                config_path=config.root_dir / "configs" / "moscow_demo.json",
                                models_dir=st.session_state["models_dir_input"],
                                artifacts_dir=st.session_state["artifacts_dir_input"],
                                scripts_dir=st.session_state["scripts_dir_input"],
                                outputs_dir=st.session_state["outputs_dir_input"],
                            )
                            st.success("Пути сохранены в configs/moscow_demo.json")
                        except Exception as exc:
                            st.error(f"Не удалось сохранить пути: {exc}")'''

    pattern = (
        r'                st\.markdown\("\*\*Пути проекта\*\*"\)'
        r'.*?'
        r'(?=\n\n            summary = build_model_summary\(config\))'
    )

    text, count = re.subn(
        pattern,
        new_paths_block,
        text,
        flags=re.DOTALL,
        count=1,
    )

    if count == 0:
        print("[warn] Не удалось найти блок sidebar с путями через regex.")
        print("Но попробуем добавить новый блок перед summary.")

        text = text.replace(
            "\n            summary = build_model_summary(config)",
            "\n" + new_paths_block + "\n\n            summary = build_model_summary(config)",
            1,
        )

    # 5. Применяем runtime-пути перед построением данных
    old_block = '''            summary = build_model_summary(config)
            combined = build_combined_points(config)
            artifacts = list_artifacts(config)
            scripts = list_scripts(config)'''

    new_block = '''            config = apply_runtime_paths(config)

            summary = build_model_summary(config)
            combined = build_combined_points(config)
            artifacts = list_artifacts(config)
            scripts = list_scripts(config)'''

    if "config = apply_runtime_paths(config)" not in text:
        text = text.replace(old_block, new_block)

    DASHBOARD_PATH.write_text(text, encoding="utf-8")

    print("[ok] Sidebar с путями обновлён.")
    print("Запусти: streamlit run app.py")


if __name__ == "__main__":
    main()