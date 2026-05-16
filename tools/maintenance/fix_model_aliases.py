import json
from pathlib import Path

config_path = Path("configs/moscow_demo.json")

if not config_path.exists():
    raise FileNotFoundError("Не найден configs/moscow_demo.json")

config = json.loads(config_path.read_text(encoding="utf-8"))

config["model_aliases"] = {
    "coverage": [
        "pvz_selected_20",
        "selected_20",
        "coverage",
        "maxcoverage",
        "max_coverage",
        "greedy"
    ],
    "mean_time": [
        "pvz_selected_mean_k20",
        "selected_mean",
        "mean_k20",
        "mean_time",
        "min_mean",
        "time"
    ],
    "effective": [
        "pvz_selected_effective_k20",
        "selected_effective",
        "effective_k20",
        "effective",
        "eff",
        "max_effective"
    ],
    "compromise": [
        "pvz_selected_effective_keep_zelenograd_k20",
        "keep_zelenograd",
        "zelenograd",
        "compromise",
        "limited"
    ],
    "kmax": [
        "pvz_selected_kmax",
        "kmax"
    ],
    "k20_to_k30": [
        "pvz_added_k20_to_k30",
        "k20_to_k30",
        "added"
    ]
}

config_path.write_text(
    json.dumps(config, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print("Алиасы моделей обновлены.")
