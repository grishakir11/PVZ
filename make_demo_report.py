from pathlib import Path

from pvz_system.config import load_config
from pvz_system.reporting import make_markdown_report


def main() -> None:
    config = load_config()
    config.outputs_dir.mkdir(parents=True, exist_ok=True)

    report = make_markdown_report(config)
    output_path = config.outputs_dir / "pvz_system_report.md"

    output_path.write_text(report, encoding="utf-8")

    print(f"Отчёт сохранён: {output_path}")


if __name__ == "__main__":
    main()
