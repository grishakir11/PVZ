from pathlib import Path
import textwrap


TARGET = Path("pvz_system/ui_path_state.py")


CODE = r'''
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
    paths = default_paths(config)

    if not UI_PATHS_FILE.exists():
        return paths

    try:
        raw = json.loads(UI_PATHS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return paths

    for key in paths:
        if key in raw and str(raw[key]).strip():
            paths[key] = str(raw[key])

    return paths


def ensure_path_state(config) -> None:
    """
    Инициализирует path-поля ДО создания виджетов.

    Важно:
    - нельзя менять st.session_state[key] после создания text_input с этим key;
    - поэтому эта функция должна вызываться только перед отрисовкой виджетов;
    - если ключ уже существует, не трогаем его.
    """
    saved = load_saved_paths(config)

    for name, key in PATH_KEYS.items():
        if key not in st.session_state:
            st.session_state[key] = saved[name]


def get_path_value(config, name: str) -> str:
    """
    Возвращает значение пути без записи в session_state.
    Это безопасно вызывать после создания виджетов.
    """
    saved = load_saved_paths(config)
    key = PATH_KEYS[name]

    value = st.session_state.get(key)

    if value is None or not str(value).strip():
        return saved[name]

    return str(value)


def save_paths(config) -> None:
    """
    Сохраняет текущие значения из session_state в configs/ui_paths.json.
    """
    UI_PATHS_FILE.parent.mkdir(parents=True, exist_ok=True)

    data = {
        name: to_config_value(config.root_dir, get_path_value(config, name))
        for name in PATH_KEYS
    }

    UI_PATHS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def apply_paths(config):
    """
    Возвращает копию config с путями из st.session_state.

    Важно: эта функция НЕ изменяет st.session_state.
    Поэтому её можно безопасно вызывать после создания text_input.
    """
    return replace(
        config,
        models_dir=resolve_path(
            config.root_dir,
            get_path_value(config, "models_dir"),
        ),
        artifacts_dir=resolve_path(
            config.root_dir,
            get_path_value(config, "artifacts_dir"),
        ),
        scripts_dir=resolve_path(
            config.root_dir,
            get_path_value(config, "scripts_dir"),
        ),
        outputs_dir=resolve_path(
            config.root_dir,
            get_path_value(config, "outputs_dir"),
        ),
    )


def path_status(path: Path) -> str:
    return "✅ найдена" if path.exists() else "❌ не найдена"


def render_path_editor(config, location: str = "sidebar"):
    """
    Общий редактор путей для основной страницы и страницы pipeline.
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


def main() -> None:
    TARGET.write_text(
        textwrap.dedent(CODE).strip() + "\n",
        encoding="utf-8",
    )

    print("[ok] pvz_system/ui_path_state.py исправлен")
    print("Теперь останови Streamlit через Ctrl+C и запусти заново:")
    print("  streamlit run app.py")


if __name__ == "__main__":
    main()
    