from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query, Request
from fastapi.responses import ORJSONResponse

from .. import config
from ..errors import ApiError
from ..schemas import AdjustRequest, ErrorBody
from ..services import external, regime, scenarios

router = APIRouter()
_ERR = {404: {"model": ErrorBody}, 422: {"model": ErrorBody}}


@router.post("/forecast/adjusted", summary="Прогноз с корректирующими коэффициентами (пересчёт на лету)", responses=_ERR)
def forecast_adjusted(body: AdjustRequest, request: Request):
    return ORJSONResponse(scenarios.adjusted(request.app.state.store, body))


@router.get("/factors", summary="Пределы и ориентиры для коэффициентов (измеренные и экспертные)")
def factors(request: Request):
    return ORJSONResponse(external.presets(request.app.state.store.external))


@router.get("/calendar", summary="Производственный календарь РФ на период и поправка на праздничные дни", responses=_ERR)
def calendar(
    request: Request,
    start: date = Query(config.FORECAST_START, description="Начало периода"),
    end: date = Query(config.FORECAST_END, description="Конец периода"),
):
    ext = request.app.state.store.external
    if start > end:
        raise ApiError(400, "Дата начала позже даты окончания", "bad_range")
    days = external.calendar_days(ext, start, end)
    if not days:
        raise ApiError(422, "Календарь есть только за 2025 год: запустите python -m analysis.external_effects", "out_of_range")
    return ORJSONResponse({"source": external.SOURCES["calendar"], "holiday_factor": round(ext.holiday_factor, 4), "days": days})


@router.get("/forecast/year", summary="Годовой горизонт: профиль 2025 и сценарий на 2026", responses=_ERR)
def forecast_year(
    request: Request,
    route: int | None = Query(None, description="Номер маршрута; без значения — все"),
    growth: float = Query(1.0, ge=0.5, le=1.5, description="Множитель роста для сценария 2026"),
):
    return ORJSONResponse(scenarios.year_outlook(request.app.state.store, route, growth))


@router.get("/regime", summary="Структурные сдвиги режима «маршрут × день недели», найденные по истории")
def regime_shifts(request: Request):
    cells = request.app.state.store.regime
    return ORJSONResponse({"method": regime.METHOD, "weeks": regime.WEEKS, "thresholds": [regime.LOW, regime.HIGH], "cells": cells,
                           "note": "Множитель = уровень последних недель к средней за всю историю. Применяется поправкой regime в /forecast, /export и /forecast/adjusted."})


@router.get("/weather", summary="Погода по архиву Open-Meteo и множитель дня (по измеренным эффектам)", responses=_ERR)
def weather(
    request: Request,
    start: date = Query(config.FORECAST_START, description="Начало периода"),
    end: date = Query(config.FORECAST_END, description="Конец периода"),
):
    ext = request.app.state.store.external
    if start > end:
        raise ApiError(400, "Дата начала позже даты окончания", "bad_range")
    days = external.weather_days(ext, start, end)
    if not days:
        raise ApiError(422, "Погода есть только за 2025 год: запустите python -m analysis.external_effects", "out_of_range")
    return ORJSONResponse({
        "source": external.SOURCES["weather"],
        "note": "Фактическая погода из архива, а не прогноз погоды: на двухмесячном горизонте погоду предсказать нельзя. Эффект значим статистически, но точность прогноза на отложенных периодах не повышает.",
        "rain_factor": round(1 + ext.effects["rain"]["effect"], 4) if ext.effects.get("rain", {}).get("effect") is not None else None,
        "snow_factor": round(1 + ext.effects["snow"]["effect"], 4) if ext.effects.get("snow", {}).get("effect") is not None else None,
        "days": days,
    })
