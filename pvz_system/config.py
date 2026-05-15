from dataclasses import dataclass
from pathlib import Path
import json


@dataclass
class ProjectConfig:
    project_name: str
    description: str
    root_dir: Path
    models_dir: Path
    scripts_dir: Path
    artifacts_dir: Path
    outputs_dir: Path
    default_k: int
    default_model: str
    model_aliases: dict


def load_config(config_path: str = "configs/moscow_demo.json") -> ProjectConfig:
    root_dir = Path.cwd()
    path = root_dir / config_path

    if not path.exists():
        raise FileNotFoundError(
            f"Не найден конфигурационный файл: {path}. "
            f"Сначала запустите bootstrap_pvz_system.py"
        )

    raw = json.loads(path.read_text(encoding="utf-8"))
    paths = raw.get("paths", {})
    demo = raw.get("demo", {})

    return ProjectConfig(
        project_name=raw.get("project_name", "PVZ Location System"),
        description=raw.get("description", ""),
        root_dir=root_dir,
        models_dir=root_dir / paths.get("models_dir", "pvz_project/models"),
        scripts_dir=root_dir / paths.get("scripts_dir", "scripts/final"),
        artifacts_dir=root_dir / paths.get(
            "artifacts_dir",
            "pvz_project/deliverables/thesis_artifacts"
        ),
        outputs_dir=root_dir / paths.get("outputs_dir", "outputs"),
        default_k=int(demo.get("default_k", 20)),
        default_model=demo.get("default_model", "coverage"),
        model_aliases=raw.get("model_aliases", {})
    )
