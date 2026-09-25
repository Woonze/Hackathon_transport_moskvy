from __future__ import annotations

from datetime import date

from .. import config
from ..errors import ApiError
from ..schemas import Granularity, Kind
from ..store import DataStore
from . import series
from .stopmodel import METHOD

_PUBLIC = ("route", "direction", "sequence", "stop_id", "name", "lat", "lon", "district", "is_hub")


def _source(store: DataStore, kind: Kind):
    return store.forecast if kind is Kind.forecast else store.history


def _stop_dict(s: dict) -> dict:
    return {k: s[k] for k in _PUBLIC}


def require_route(store: DataStore, route: int) -> dict[int, list[dict]]:
    series.resolve_route(store, route)
    if route not in store.stops:
        available = ", ".join(map(str, sorted(store.stops))) or "нет"
        raise ApiError(404, f"Для маршрута {route} нет остановок в справочнике. Остановки есть у маршрутов: {available}", "stops_not_available")
    return store.stops[route]


def _hours(hour_from: int, hour_to: int) -> None:
    if hour_from > hour_to:
        raise ApiError(422, "Час начала позже часа окончания", "bad_hours")


def route_total(store: DataStore, kind: Kind, route: int, start: date, end: date, hour_from: int, hour_to: int) -> int:
    series.validate(store, kind.value, start, end, route, Granularity.day, limit_hours=False)
    _hours(hour_from, hour_to)
    src = _source(store, kind)
    lo, hi = src.span(start, end)
    return int(src.values[src.route_index[route], lo:hi, hour_from : hour_to + 1].sum())


def catalog(store: DataStore, route: int | None) -> dict:
    if route is not None:
        require_route(store, route)
    routes = [route] if route is not None else sorted(store.stops)
    stops = [
        {**_stop_dict(s), "boarding_share": round(s["board_share"], 5)}
        for r in routes
        for d in sorted(store.stops[r])
        for s in store.stops[r][d]
    ]
    return {"estimated": True, "method": METHOD, "weights": config.STOP_WEIGHTS, "routes": routes, "stops": stops}


def flow(store: DataStore, kind: Kind, route: int, start: date, end: date, hour_from: int, hour_to: int) -> dict:
    directions = require_route(store, route)
    total = route_total(store, kind, route, start, end, hour_from, hour_to)
    stops = [
        {**_stop_dict(s), "boardings": round(total * s["board_share"]), "share": round(s["board_share"], 5)}
        for d in sorted(directions)
        for s in directions[d]
    ]
    return {"estimated": True, "method": METHOD, "kind": kind.value, "route": route, "route_total": total, "stops": stops}


def segments(store: DataStore, kind: Kind, route: int, start: date, end: date, hour_from: int, hour_to: int) -> dict:
    directions = require_route(store, route)
    total = route_total(store, kind, route, start, end, hour_from, hour_to)
    out = []
    for d in sorted(directions):
        stops = directions[d]
        for a, b in zip(stops, stops[1:]):
            out.append({
                "route": route, "direction": d, "sequence": a["sequence"],
                "from": _stop_dict(a), "to": _stop_dict(b),
                "passengers": round(total * a["onboard_after"]),
            })
    return {"estimated": True, "method": METHOD, "kind": kind.value, "route": route, "route_total": total,
            "segments": out, "peak": max(out, key=lambda s: s["passengers"]) if out else None}


def stop_series(store: DataStore, kind: Kind, stop_id: str, start: date, end: date, granularity: Granularity,
                route: int | None = None) -> dict:
    series.resolve_route(store, route)
    shares = {
        r: sum(s["board_share"] for d in dirs.values() for s in d if s["stop_id"] == stop_id)
        for r, dirs in store.stops.items()
        if route is None or r == route
    }
    shares = {r: v for r, v in shares.items() if v > 0}
    if not shares:
        label = f" на маршруте {route}" if route is not None else ""
        raise ApiError(404, f"Остановка {stop_id}{label} не найдена", "stop_not_found")
    series.validate(store, kind.value, start, end, route, granularity)
    acc: dict[tuple, float] = {}
    for route, share in shares.items():
        for row in series.rows(store, _source(store, kind), start, end, route, granularity):
            key = tuple(row[k] for k in ("month", "date", "hour") if k in row)
            acc[key] = acc.get(key, 0.0) + row["passengers"] * share
    names = ("month",) if granularity is Granularity.month else ("date", "hour") if granularity is Granularity.hour else ("date",)
    ref = next(s for dirs in store.stops.values() for d in dirs.values() for s in d if s["stop_id"] == stop_id)
    return {
        "estimated": True, "method": METHOD, "kind": kind.value, "stop_id": stop_id, "name": ref["name"],
        "routes": sorted(shares), "data": [dict(zip(names, key), passengers=round(v)) for key, v in sorted(acc.items())],
    }
