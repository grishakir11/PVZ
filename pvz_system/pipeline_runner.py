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
