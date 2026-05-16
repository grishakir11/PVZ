from pathlib import Path
import textwrap


def write_file(path: str, content: str) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
    print(f"[ok] {path}")


def patch_file(path: str, replacements: list[tuple[str, str]]) -> None:
    file_path = Path(path)

    if not file_path.exists():
        print(f"[skip] не найден файл: {path}")
        return

    text = file_path.read_text(encoding="utf-8")

    for old, new in replacements:
        if old in text:
            text = text.replace(old, new)
        else:
            print(f"[warn] не найден фрагмент в {path}: {old[:80]}...")

    file_path.write_text(text, encoding="utf-8")
    print(f"[ok] patched {path}")


def main() -> None:
    write_file(
        "pvz_system/ui_path_state.py",
        r'''
        from dataclasses import replace
        from pathlib import Path
        import json

        import streamlit as st


        UI_PATHS_FILE = Path("configs/ui_paths.json")


        PATH_KEYS = {
            "models_dir": "models_dir_input",
            "artifacts_dir": "artifacts_dir_input",
            "scripts_dir": "scripts_dir_input",
            "outputs_dir": "outputs_dir_input",
        }


        def resolve_path(root_dir: Path, value: str) -> Path:
            value = str(value).strip()

            if not value:
                return root_dir

            path = Path(value).expanduser()

            if path.is_absolute():
                return path

            return root_dir / path


        def to_config_value(root_dir: Path, value: str) -> str:
            path = resolve_path(root_dir, value)

            try:
                return str(path.relative_to(root_dir)).replace("\\", "/")
            except ValueError:
                return str(path)


        def default_paths(config) -> dict:
            return {
                "models_dir": str(config.models_dir),
                "artifacts_dir": str(config.artifacts_dir),
                "scripts_dir": str(config.scripts_dir),
                "outputs_dir": str(config.outputs_dir),
            }


        def load_saved_paths(config) -> dict:
            """
            Загружает пути из configs/ui_paths.json.
            Если файла нет — берёт пути из основного конфига.
            """
            if not UI_PATHS_FILE.exists():
                return default_paths(config)

            try:
                raw = json.loads(UI_PATHS_FILE.read_text(encoding="utf-8"))
            except Exception:
                return default_paths(config)

            paths = default_paths(config)
            paths.update({k: str(v) for k, v in raw.items() if k in paths})
            return paths


        def save_paths(config) -> None:
            """
            Сохраняет текущие значения из session_state в configs/ui_paths.json.
            """
            UI_PATHS_FILE.parent.mkdir(parents=True, exist_ok=True)

            data = {
                name: to_config_value(config.root_dir, st.session_state[key])
                for name, key in PATH_KEYS.items()
            }

            UI_PATHS_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )


        def ensure_path_state(config) -> None:
            """
            Гарантирует, что все path-поля есть в st.session_state.

            Важно: не используем один общий флаг initialized,
            потому что при переключении страниц часть ключей может исчезнуть
            или ещё не быть создана.
            """
            saved = load_saved_paths(config)

            for name, key in PATH_KEYS.items():
                if key not in st.session_state or not str(st.session_state[key]).strip():
                    st.session_state[key] = saved[name]


        def apply_paths(config):
            """
            Возвращает копию config с путями из st.session_state.
            """
            ensure_path_state(config)

            return replace(
                config,
                models_dir=resolve_path(config.root_dir, st.session_state["models_dir_input"]),
                artifacts_dir=resolve_path(config.root_dir, st.session_state["artifacts_dir_input"]),
                scripts_dir=resolve_path(config.root_dir, st.session_state["scripts_dir_input"]),
                outputs_dir=resolve_path(config.root_dir, st.session_state["outputs_dir_input"]),
            )


        def path_status(path: Path) -> str:
            return "✅ найдена" if path.exists() else "❌ не найдена"


        def render_path_editor(config, location="sidebar"):
            """
            Рисует общий редактор путей.
            Его можно использовать и в главном app, и на странице pipeline.
            """
            ensure_path_state(config)

            target = st.sidebar if location == "sidebar" else st

            target.subheader("Пути проекта")
            target.caption("Можно указать абсолютный путь или путь относительно корня проекта.")

            target.text_input(
                "Папка моделей",
                key="models_dir_input",
                help="Например: pvz_project/models",
            )

            target.text_input(
                "Папка артефактов",
                key="artifacts_dir_input",
                help="Например: pvz_project/deliverables/thesis_artifacts",
            )

            target.text_input(
                "Папка финальных скриптов",
                key="scripts_dir_input",
                help="Например: scripts/final",
            )

            target.text_input(
                "Папка выходных файлов",
                key="outputs_dir_input",
                help="Например: outputs",
            )

            col1, col2 = target.columns(2)

            with col1:
                if st.button("Применить", use_container_width=True, key=f"apply_paths_{location}"):
                    save_paths(config)
                    st.rerun()

            with col2:
                if st.button("Сохранить", use_container_width=True, key=f"save_paths_{location}"):
                    save_paths(config)
                    target.success("Пути сохранены")

            runtime_config = apply_paths(config)

            target.divider()
            target.caption("Проверка путей")

            target.write(f"Модели: {path_status(runtime_config.models_dir)}")
            target.write(f"Артефакты: {path_status(runtime_config.artifacts_dir)}")
            target.write(f"Скрипты: {path_status(runtime_config.scripts_dir)}")
            target.write(f"Выходные файлы: {path_status(runtime_config.outputs_dir)}")

            return runtime_config
        '''
    )

    # Патчим dashboard_pro.py: заменяем локальную логику путей на общий модуль.
    dashboard = Path("pvz_system/interface/dashboard_pro.py")

    if dashboard.exists():
        text = dashboard.read_text(encoding="utf-8")

        if "from pvz_system.ui_path_state import" not in text:
            text = text.replace(
                "from pvz_system.config import load_config\n",
                "from pvz_system.config import load_config\n"
                "from pvz_system.ui_path_state import render_path_editor\n",
            )

        # Заменяем функцию render_sidebar_paths целиком более простой версией.
        start = text.find("def render_sidebar_paths(base_config):")
        end = text.find("\ndef run_dashboard() -> None:", start)

        if start != -1 and end != -1:
            new_func = r'''
def render_sidebar_paths(base_config):
    st.sidebar.header("Управление")

    selected_model = st.sidebar.selectbox(
        "Модель размещения",
        options=list(MODEL_LABELS.keys()),
        format_func=lambda key: MODEL_LABELS[key],
    )

    st.sidebar.divider()

    runtime_config = render_path_editor(base_config, location="sidebar")

    return selected_model, runtime_config
'''
            text = text[:start] + new_func + text[end:]
        else:
            print("[warn] Не нашёл render_sidebar_paths в dashboard_pro.py")

        dashboard.write_text(text, encoding="utf-8")
        print("[ok] dashboard_pro.py обновлён")
    else:
        print("[skip] dashboard_pro.py не найден")

    # Патчим страницу pipeline: она тоже должна брать пути из общего состояния.
    pipeline_page = Path("pages/01_Полный_расчёт_pipeline.py")

    if pipeline_page.exists():
        text = pipeline_page.read_text(encoding="utf-8")

        if "from pvz_system.ui_path_state import" not in text:
            text = text.replace(
                "from pvz_system.config import load_config\n",
                "from pvz_system.config import load_config\n"
                "from pvz_system.ui_path_state import render_path_editor\n",
            )

        old = '''config = load_config()
        root_dir = config.root_dir'''
        new = '''base_config = load_config()

        with st.sidebar:
            st.header("Настройки путей")
            config = render_path_editor(base_config, location="pipeline_sidebar")

        root_dir = config.root_dir'''

        if old in text:
            text = text.replace(old, new)
        else:
            print("[warn] Не нашёл блок config/root_dir в pipeline page")

        pipeline_page.write_text(text, encoding="utf-8")
        print("[ok] pipeline page обновлена")
    else:
        print("[skip] pipeline page не найдена")

    print()
    print("Готово.")
    print("Теперь останови Streamlit через Ctrl+C и запусти заново:")
    print("  streamlit run app.py")


if __name__ == "__main__":
    main()