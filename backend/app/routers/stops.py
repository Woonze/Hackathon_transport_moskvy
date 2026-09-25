from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query, Request
from fastapi.responses import ORJSONResponse

from .. import config
from ..schemas import ErrorBody, Granularity, Kind
from ..services import stops as svc

router = APIRouter(prefix="/stops", tags=["stops"])
_ERR = {404: {"model": ErrorBody}, 422: {"model": ErrorBody}}
_KIND = Query(Kind.forecast, description="forecast — прогноз, history — история")
_ROUTE = Query(..., description="Номер маршрута")
_FROM = Query(0, ge=0, le=23, description="С какого часа")
_TO = Query(23, ge=0, le=23, description="По какой час включительно")


def _period(kind: Kind, start: date | None, end: date | None, request: Request) -> tuple[date, date]:
    from ..services import series

    lo, hi = series.bounds(request.app.state.store, kind.value)
    return start or lo, end or hi


@router.get("", summary="Остановки маршрутов со справочником и оценочными долями посадок", responses=_ERR)
def stops(request: Request, route: int | None = Query(None, description="Номер маршрута; без значения — все с остановками")):
    return ORJSONResponse(svc.catalog(request.app.state.store, route))


@router.get("/flow", summary="Оценка посадок по остановкам маршрута", responses=_ERR)
def flow(request: Request, route: int = _ROUTE, kind: Kind = _KIND, start: date | None = None, end: date | None = None,
         hour_from: int = _FROM, hour_to: int = _TO):
    s, e = _period(kind, start, end, request)
    return ORJSONResponse(svc.flow(request.app.state.store, kind, route, s, e, hour_from, hour_to))


@router.get("/segments", summary="Оценка загрузки участков между соседними остановками", responses=_ERR)
def segments(request: Request, route: int = _ROUTE, kind: Kind = _KIND, start: date | None = None, end: date | None = None,
             hour_from: int = _FROM, hour_to: int = _TO):
    s, e = _period(kind, start, end, request)
    return ORJSONResponse(svc.segments(request.app.state.store, kind, route, s, e, hour_from, hour_to))


@router.get("/{stop_id}/series", summary="Оценка динамики посадок на остановке", responses=_ERR)
def stop_series(request: Request, stop_id: str, kind: Kind = _KIND, start: date | None = None, end: date | None = None,
                granularity: Granularity = Query(Granularity.day)):
    s, e = _period(kind, start, end, request)
    return ORJSONResponse(svc.stop_series(request.app.state.store, kind, stop_id, s, e, granularity))
