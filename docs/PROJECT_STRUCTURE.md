# Структура проекта

    PVZ/
      app.py
      main.py
      make_demo_report.py
      README.md

      configs/
        moscow_demo.json

      pvz_system/
        config.py
        data_io.py
        reporting.py
        pipeline_runner.py
        runtime_paths.py
        ui_path_state.py
        evaluation/
        optimization/
        interface/

      pages/
        01_Полный_расчёт_pipeline.py

      scripts/
        final/
        archive/

      pvz_project/
        models/
        deliverables/

      docs/
        ARCHITECTURE.md
        RUN_GUIDE.md
        DEMO_SCENARIO.md
        PROGRAM_IMPLEMENTATION_TEXT.md
        PROJECT_STRUCTURE.md

      tools/
        maintenance/

## Назначение основных папок

- `pvz_system` — модульная программная оболочка проекта.
- `scripts/final` — финальные расчётные скрипты исходного GIS-pipeline.
- `pvz_project/models` — рассчитанные конфигурации ПВЗ.
- `pvz_project/deliverables` — итоговые визуализации и таблицы.
- `pages` — дополнительные страницы Streamlit.
- `docs` — документация для запуска, защиты и описания архитектуры.
- `tools/maintenance` — служебные скрипты, использовавшиеся при доработке проекта.
