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
        available = "\n".join(str(p) for p in list_available_models(config))
        raise FileNotFoundError(
            f"Не удалось найти CSV для модели '{model_name}'.\n"
            f"Папка поиска: {config.models_dir}\n"
            f"Найденные CSV:\n{available}"
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
