# Руководство по запуску

## 1. Установка зависимостей

    pip install -r requirements.txt
    pip install -r requirements-app.txt

## 2. Проверка проекта

    python main.py status

## 3. Запуск интерфейса

    streamlit run app.py

## 4. Основные разделы интерфейса

- **Обзор** — назначение системы, архитектура, реализованные модели.
- **Модель** — просмотр выбранной конфигурации ПВЗ.
- **Сравнение** — сопоставление четырёх моделей размещения.
- **Артефакты** — просмотр итоговых карт, таблиц и графиков.
- **Отчёт** — формирование краткого отчёта по программной системе.
- **Полный расчёт pipeline** — страница для запуска расчётных этапов.

## 5. Консольные команды

    python main.py list-models
    python main.py compare-models
    python main.py list-artifacts
    python main.py list-scripts
    python make_demo_report.py
