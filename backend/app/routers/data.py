from __future__ import annotations

import os
from datetime import date

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse, ORJSONResponse

from .. import config
from ..schemas import SERIES_DOC, ErrorBody, ExportFormat, Granularity, Kind, RouteInfo, WeekdayAverage
from ..services import export as export_service
from ..services import series

router = APIRouter()


def _json(body: bytes) -> Response:
    return Response(body, media_type="application/json")


@router.get("/health", summary="Состояние сервиса")
def health(request: Request):
    store = request.app.state.store
    return {
        "status": "ok",
        "version": config.API_VERSION,
        "worker_pid": os.getpid(),  # какой воркер ответил: нужно для диагностики нескольких воркеров
        "forecast_rows": store.forecast_rows,
        "routes": len(store.routes),
        "ingest_protected": bool(config.INGEST_API_KEY),
        "history_period": [config.HISTORY_START.isoformat(), store.history_end.isoformat()],
        "forecast_period": [config.FORECAST_START.isoformat(), config.FORECAST_END.isoformat()],
    }


@router.get("/routes", summary="Маршруты с итогами истории и прогноза", response_model=list[RouteInfo])
def routes(request: Request):
    return ORJSONResponse(request.app.state.store.route_summary)


@router.get("/forecast", summary="Прогноз посадок", responses=SERIES_DOC)
def forecast(
    request: Request,
    start: date = Query(config.FORECAST_START, description="Начало периода"),
    end: date = Query(config.FORECAST_END, description="Конец периода"),
    route: int | None = Query(None, description="Номер маршрута; без значения — все"),
    granularity: Granularity = Query(Granularity.day, description="day, hour или month"),
):
    return _json(series.series_json(request.app.state.store, "forecast", start, end, route, granularity))


@router.get("/history", summary="История посадок", responses=SERIES_DOC)
def history(
    request: Request,
    start: date | None = Query(None, description="Начало периода; по умолчанию начало истории"),
    end: date | None = Query(None, description="Конец периода; по умолчанию последний день с данными"),
    route: int | None = Query(None, description="Номер маршрута; без значения — все"),
    granularity: Granularity = Query(Granularity.day, description="day, hour или month"),
):
    store = request.app.state.store
    lo, hi = series.bounds(store, "history")
    return _json(series.series_json(store, "history", start or lo, end or hi, route, granularity))


@router.get(
    "/history/weekday-average",
    summary="Средние посадки по дням недели (сентябрь–октябрь)",
    response_model=list[WeekdayAverage],
    responses={404: {"model": ErrorBody}},
)
def weekday_average(request: Request, route: int | None = None):
    store = request.app.state.store
    series.resolve_route(store, route)
    return ORJSONResponse([r for r in store.weekday_average if route is None or r["route"] == route])


@router.get("/map", summary="Геометрия маршрутов и остановки (GeoJSON)")
def route_map():
    path = config.ARTIFACTS / "routes.geojson"
    if not path.exists():
        return ORJSONResponse({"type": "FeatureCollection", "features": []})
    return FileResponse(path, media_type="application/geo+json")


@router.get(
    "/export",
    summary="Выгрузка прогноза или истории (CSV/XLSX) с учётом фильтров",
    responses={200: {"content": {"text/csv": {}, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}}, **{k: v for k, v in SERIES_DOC.items() if k != 200}},
)
def export(
    request: Request,
    kind: Kind = Query(Kind.forecast, description="forecast — прогноз, history — история"),
    format: ExportFormat = Query(ExportFormat.csv, description="csv или xlsx"),
    start: date | None = Query(None, description="Начало периода; по умолчанию начало доступных данных"),
    end: date | None = Query(None, description="Конец периода; по умолчанию конец доступных данных"),
    route: int | None = Query(None, description="Номер маршрута; без значения — все"),
    granularity: Granularity = Query(Granularity.hour, description="hour, day или month"),
):
    store = request.app.state.store
    lo, hi = series.bounds(store, kind.value)
    body, mime, name = export_service.build(store, kind, format, start or lo, end or hi, route, granularity)
    return Response(body, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})
