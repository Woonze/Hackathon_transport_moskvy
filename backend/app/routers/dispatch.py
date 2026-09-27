from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query, Request
from fastapi.responses import ORJSONResponse

from ..schemas import ErrorBody
from ..services import dispatch

router = APIRouter(prefix="/dispatch", tags=["dispatch"])
_ERR = {404: {"model": ErrorBody}, 422: {"model": ErrorBody}}
_ROUTE = Query(None, description="Номер маршрута; без значения — все маршруты")
_CORR = Query(dispatch.DEFAULT_CORRECTIONS, description="Поправки через запятую: calendar, regime, weather; пустое значение — прогноз модели как есть")


@router.get("/day", summary="Сводка диспетчера на день: пики, загрузка по часам, горячие участки, расчёт вагонов", responses=_ERR)
def day_plan(
    request: Request,
    day: date = Query(..., alias="date", description="День из прогнозного периода"),
    route: int | None = _ROUTE,
    corrections: str = _CORR,
    capacity: float | None = Query(None, gt=0, le=100000, description="Сколько посадок за час выдерживает один вагон (задаёт пользователь)"),
    vehicles: int | None = Query(None, ge=1, le=1000, description="Сколько вагонов на линии; вместе с capacity даёт загрузку и нехватку вагонов"),
):
    return ORJSONResponse(dispatch.day_plan(request.app.state.store, route, day, corrections, capacity, vehicles))


@router.get("/savings", summary="Дни с пониженным спросом, где возможен пересмотр выпуска", responses=_ERR)
def savings(
    request: Request,
    route: int | None = _ROUTE,
    corrections: str = _CORR,
    threshold: float = Query(0.25, gt=0, lt=1, description="Насколько прогноз с поправками должен быть ниже прогноза модели"),
    limit: int = Query(30, ge=1, le=200, description="Сколько дней вернуть"),
):
    return ORJSONResponse(dispatch.savings(request.app.state.store, route, corrections, threshold, limit))
