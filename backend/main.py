from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, ORJSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "dataset"
ARTIFACTS = ROOT / "artifacts"
PREDICTIONS = pd.read_csv(ROOT / "submission.csv", sep=";", parse_dates=["date"])
HISTORY = pd.concat(
    [
        pd.read_csv(DATA / "labels" / "labels_day_train.csv", sep=";"),
        pd.read_csv(DATA / "labels" / "labels_day_test.csv", sep=";"),
    ],
    ignore_index=True,
)
HISTORY["date"] = pd.to_datetime(HISTORY["date"])
HISTORY = HISTORY.rename(columns={"boardings": "passengers"})

PREDICTION_ROWS = [
    {"route": int(r.route), "date": r.date.strftime("%Y-%m-%d"), "hour": int(r.hour), "passengers": int(r.prediction)}
    for r in PREDICTIONS.itertuples(index=False)
]
PREDICTION_DAILY_FRAME = PREDICTIONS.groupby(["route", "date"], as_index=False)["prediction"].sum()
PREDICTION_DAILY = [
    {"route": int(r.route), "date": r.date.strftime("%Y-%m-%d"), "passengers": int(r.prediction)}
    for r in PREDICTION_DAILY_FRAME.itertuples(index=False)
]
HISTORY_HOURLY = [
    {"route": int(r.route), "date": r.date.strftime("%Y-%m-%d"), "hour": int(r.hour), "passengers": int(r.passengers)}
    for r in HISTORY.itertuples(index=False)
]
HISTORY_DAILY_FRAME = HISTORY.groupby(["route", "date"], as_index=False)["passengers"].sum()
HISTORY_DAILY = [
    {"route": int(r.route), "date": r.date.strftime("%Y-%m-%d"), "passengers": int(r.passengers)}
    for r in HISTORY_DAILY_FRAME.itertuples(index=False)
]

# Dense route/day grid is only 3,040 rows and makes missing zero-passenger days explicit.
route_ids = sorted(PREDICTIONS["route"].unique().tolist())
dates = pd.date_range("2025-09-01", "2025-10-31", freq="D")
recent_grid = pd.MultiIndex.from_product([route_ids, dates], names=["route", "date"]).to_frame(index=False)
recent_daily = recent_grid.merge(HISTORY_DAILY_FRAME, on=["route", "date"], how="left").fillna({"passengers": 0})
recent_daily["weekday"] = recent_daily["date"].dt.dayofweek
WEEKDAY_AVERAGES = [
    {"route": int(route), "weekday": int(weekday), "passengers": float(value)}
    for (route, weekday), value in recent_daily.groupby(["route", "weekday"])["passengers"].mean().items()
]

app = FastAPI(title="Трамвайный прогноз Москвы", version="1.0.0", default_response_class=ORJSONResponse)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def date_filter(rows: list[dict], start: date, end: date, route: int | None):
    start_text, end_text = start.isoformat(), end.isoformat()
    return [row for row in rows if start_text <= row["date"] <= end_text and (route is None or row["route"] == route)]


@app.get("/api/health")
def health():
    return {"status": "ok", "forecast_rows": len(PREDICTION_ROWS)}


@app.get("/api/routes")
def routes():
    totals = PREDICTIONS.groupby("route")["prediction"].sum().to_dict()
    historical = HISTORY.groupby("route")["passengers"].sum().to_dict()
    return [
        {
            "id": int(route),
            "name": f"Маршрут {route}",
            "historical_total": int(historical.get(route, 0)),
            "forecast_total": int(totals.get(route, 0)),
        }
        for route in route_ids
    ]


@app.get("/api/forecast")
def forecast(
    start: date = Query(default=date(2025, 11, 1)),
    end: date = Query(default=date(2025, 12, 31)),
    route: int | None = None,
    granularity: str = Query(default="day", pattern="^(day|hour)$"),
):
    if start > end:
        raise HTTPException(status_code=400, detail="Дата начала позже даты окончания")
    span = (end - start).days + 1
    if granularity == "hour" and span > (92 if route is not None else 31):
        raise HTTPException(status_code=422, detail="Почасовой прогноз ограничен 31 днём или 92 днями для одного маршрута")
    rows = PREDICTION_DAILY if granularity == "day" else PREDICTION_ROWS
    return date_filter(rows, start, end, route)


@app.get("/api/history")
def history(
    start: date = Query(default=date(2025, 1, 1)),
    end: date = Query(default=date(2025, 10, 31)),
    route: int | None = None,
    granularity: str = Query(default="day", pattern="^(day|hour)$"),
):
    if start > end:
        raise HTTPException(status_code=400, detail="Дата начала позже даты окончания")
    span = (end - start).days + 1
    if granularity == "hour" and span > (92 if route is not None else 31):
        raise HTTPException(status_code=422, detail="Почасовая история ограничена 31 днём или 92 днями для одного маршрута")
    rows = HISTORY_DAILY if granularity == "day" else HISTORY_HOURLY
    return date_filter(rows, start, end, route)


@app.get("/api/history/weekday-average")
def weekday_average(route: int | None = None):
    return [row for row in WEEKDAY_AVERAGES if route is None or row["route"] == route]


@app.get("/api/map")
def route_map():
    path = ARTIFACTS / "routes.geojson"
    if not path.exists():
        return {"type": "FeatureCollection", "features": []}
    return FileResponse(path, media_type="application/geo+json")


@app.get("/api/export")
def export_csv():
    return FileResponse(ROOT / "submission.csv", filename="tramway_forecast.csv", media_type="text/csv; charset=utf-8")


FRONTEND = ROOT / "frontend" / "dist"
if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
