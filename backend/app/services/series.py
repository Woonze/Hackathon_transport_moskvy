from __future__ import annotations

from datetime import date

import orjson

from .. import config
from ..errors import ApiError
from ..schemas import Granularity
from ..store import DataStore, Series

_CACHE_LIMIT = 512


def bounds(store: DataStore, kind: str) -> tuple[date, date]:
    return (config.FORECAST_START, config.FORECAST_END) if kind == "forecast" else (config.HISTORY_START, store.history_end)


def resolve_route(store: DataStore, route: int | None) -> list[int]:
    if route is None:
        return list(range(len(store.routes)))
    if route not in store.history.route_index:
        raise ApiError(404, f"Маршрут {route} не найден. Доступны: {', '.join(map(str, store.routes))}", "route_not_found")
    return [store.history.route_index[route]]


def validate(store: DataStore, kind: str, start: date, end: date, route: int | None, granularity: Granularity, limit_hours: bool = True) -> None:
    lo, hi = bounds(store, kind)
    label = "Прогноз" if kind == "forecast" else "История"
    if start > end:
        raise ApiError(400, "Дата начала позже даты окончания", "bad_range")
    if end < lo or start > hi:
        raise ApiError(422, f"{label} доступен за период {lo.isoformat()} — {hi.isoformat()}", "out_of_range")
    resolve_route(store, route)
    span = (min(end, hi) - max(start, lo)).days + 1
    if limit_hours and granularity is Granularity.hour and span > (config.HOUR_LIMIT_ONE_ROUTE if route is not None else config.HOUR_LIMIT_ALL_ROUTES):
        raise ApiError(
            422,
            f"Почасовые данные ограничены периодом до {config.HOUR_LIMIT_ALL_ROUTES} дн. для всех маршрутов "
            f"или до {config.HOUR_LIMIT_ONE_ROUTE} дн. для одного маршрута",
            "range_too_wide",
        )


def rows(store: DataStore, series: Series, start: date, end: date, route: int | None, granularity: Granularity) -> list[dict]:
    """Единая выборка: её же использует экспорт, чтобы файл совпадал с экраном."""
    ris = resolve_route(store, route)
    lo, hi = series.span(start, end)
    routes, dates = series.routes, series.date_str
    cube = series.values
    if granularity is Granularity.hour:
        return [
            {"route": routes[ri], "date": dates[d], "hour": h, "passengers": int(v)}
            for ri in ris
            for d in range(lo, hi)
            for h, v in enumerate(cube[ri, d].tolist())
        ]
    daily = cube[:, lo:hi].sum(axis=2)
    if granularity is Granularity.day:
        return [
            {"route": routes[ri], "date": dates[lo + k], "passengers": int(v)}
            for ri in ris
            for k, v in enumerate(daily[ri].tolist())
        ]
    months = series.month_str
    out = []
    for ri in ris:
        acc: dict[str, int] = {}
        for k, v in enumerate(daily[ri].tolist()):
            acc[months[lo + k]] = acc.get(months[lo + k], 0) + v
        out += [{"route": routes[ri], "month": m, "passengers": v} for m, v in acc.items()]
    return out


def cached(store: DataStore, key: tuple, build):
    """Кэш на хранилище: сбрасывается вместе с ним при появлении новых данных."""
    hit = store.cache.get(key)
    if hit is None:
        if len(store.cache) >= _CACHE_LIMIT:
            store.cache.clear()
        hit = store.cache[key] = build()
    return hit


def series_json(store: DataStore, kind: str, start: date, end: date, route: int | None, granularity: Granularity) -> bytes:
    validate(store, kind, start, end, route, granularity)
    source = store.forecast if kind == "forecast" else store.history
    return cached(store, ("series", kind, start, end, route, granularity), lambda: orjson.dumps(rows(store, source, start, end, route, granularity)))
