# Отчёт по программной системе выбора локаций ПВЗ

## Назначение

Система реализует воспроизводимый GIS-пайплайн для выбора и анализа локаций пунктов выдачи заказов в Москве. Она объединяет подготовку пространственных данных, построение модели спроса, запуск моделей размещения и визуализацию результатов.

## Реализованные модели

### Максимизация охвата

Выбор локаций, обеспечивающих максимальный прирост потенциального спроса в пределах 10 минут пешего доступа.

### Минимизация среднего времени

Выбор локаций, которые сильнее всего сокращают среднее взвешенное время пешего доступа до ближайшего ПВЗ.

### Максимизация эффективного спроса

Выбор локаций, максимизирующих интегральную полезность сети с учётом снижения привлекательности ПВЗ при росте времени пути.

### Ограниченная компромиссная модель

Компромиссный вариант: часть точек фиксируется для сохранения обслуживания Зеленограда, остальные выбираются по эффективному спросу.

## Сводка по рассчитанным конфигурациям

| model | model_label | file | points | unique_districts | zelenograd_points | fixed_points | chosen_points |
| --- | --- | --- | --- | --- | --- | --- | --- |
| coverage | Максимизация охвата | pvz_project\models\pvz_selected_20.csv | 20 | 18 | 3 | 0 | 0 |
| mean_time | Минимизация среднего времени | pvz_project\models\pvz_selected_mean_k20.csv | 20 | 19 | 0 | 0 | 0 |
| effective | Максимизация эффективного спроса | pvz_project\models\pvz_selected_effective_k20.csv | 20 | 19 | 0 | 0 | 0 |
| compromise | Ограниченная компромиссная модель | pvz_project\models\pvz_selected_effective_keep_zelenograd_k20.csv | 20 | 19 | 3 | 3 | 17 |

## Пересечение выбранных локаций между моделями

Значения показывают количество совпадающих точек между конфигурациями. Координаты сравниваются с округлением.

| model | Максимизация охвата | Минимизация среднего времени | Максимизация эффективного спроса | Ограниченная компромиссная модель |
| --- | --- | --- | --- | --- |
| Максимизация охвата | 20 | 1 | 2 | 1 |
| Минимизация среднего времени | 1 | 20 | 8 | 8 |
| Максимизация эффективного спроса | 2 | 8 | 20 | 17 |
| Ограниченная компромиссная модель | 1 | 8 | 17 | 20 |

## Расчётный pipeline

Количество финальных скриптов: 15.

1. `scripts\final\00_build_walk_graph_from_pbf.py`
2. `scripts\final\01_district_features_from_osm.py`
3. `scripts\final\02b_add_walk_metrics_multipoint.py`
4. `scripts\final\05_make_demand_and_candidates_v2.py`
5. `scripts\final\06_select_pvz_greedy_maxcoverage.py`
6. `scripts\final\11_saturation_curve_share10.py`
7. `scripts\final\12_saturation_curve_time_from_home.py`
8. `scripts\final\16_select_pvz_min_mean_time_k20.py`
9. `scripts\final\18_select_pvz_max_effective_demand_k20.py`
10. `scripts\final\20_select_effective_k20_keep_zelenograd.py`
11. `scripts\final\21_compare_k20_four_networks_by_district.py`
12. `scripts\final\22_make_k20_conclusion_tables.py`
13. `scripts\final\23_make_k20_final_panels.py`
14. `scripts\final\24_make_demand_scheme_figure.py`
15. `scripts\final\25_make_candidate_scheme_figure.py`

## Итоговые артефакты

Количество найденных артефактов: 8.

- `pvz_project\deliverables\thesis_artifacts\fig_delta_mean_time_k20_k30.png`
- `pvz_project\deliverables\thesis_artifacts\fig_delta_share10_k20_k30.png`
- `pvz_project\deliverables\thesis_artifacts\fig_share10_curve.png`
- `pvz_project\deliverables\thesis_artifacts\fig_time_curve.png`
- `pvz_project\deliverables\thesis_artifacts\table_econ_scenarios.csv`
- `pvz_project\deliverables\thesis_artifacts\table_k_summary.csv`
- `pvz_project\deliverables\thesis_artifacts\top_districts_by_delta_mean_time.csv`
- `pvz_project\deliverables\thesis_artifacts\top_districts_by_delta_share10.csv`

## Вывод для защиты

Программная реализация оформляет исследовательские расчёты в виде модульной системы. Это позволяет не только получить одну конфигурацию ПВЗ, но и сравнивать несколько стратегий размещения по единой системе показателей и показывать результаты в демонстрационном интерфейсе.
