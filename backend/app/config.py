from __future__ import annotations

import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "dataset"
ARTIFACTS = ROOT / "artifacts"
FRONTEND_DIST = ROOT / "frontend" / "dist"
SUBMISSION = ROOT / "submission.csv"
LABELS = (DATASET / "labels" / "labels_day_train.csv", DATASET / "labels" / "labels_day_test.csv")

HISTORY_START, HISTORY_END = date(2025, 1, 1), date(2025, 10, 31)
FORECAST_START, FORECAST_END = date(2025, 11, 1), date(2025, 12, 31)
RECENT_START = date(2025, 9, 1)  # окно для средних по дням недели

# Почасовая выдача ограничена, чтобы один запрос не сериализовал десятки тысяч строк
HOUR_LIMIT_ALL_ROUTES = 31
HOUR_LIMIT_ONE_ROUTE = 92

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]
STOPS_FILE = ARTIFACTS / "stops.json"
EXTERNAL_DIR = ARTIFACTS / "external"  # календарь РФ, погода и измеренные эффекты (analysis/external_effects.py)
# Множители весов остановок (эвристика, не калибровалась: в данных нет посадок по остановкам)
STOP_WEIGHTS = {"first_board": 2.0, "last_board": 0.15, "hub": 1.5}
STOP_MEAN_TRIP = 8  # средняя длина поездки, остановок

# Принятые через API валидации: общий файл, который читают все воркеры
OVERLAY = Path(os.getenv("INGEST_FILE", str(ARTIFACTS / "ingested.csv")))
# Если задан, POST /ingest/validations требует заголовок X-API-Key с этим значением
INGEST_API_KEY = os.getenv("INGEST_API_KEY") or None
INGEST_MAX_RECORDS = 100_000
INGEST_MAX_DATE = date(2026, 12, 31)

API_VERSION = "1.2.0"
