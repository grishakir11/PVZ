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
