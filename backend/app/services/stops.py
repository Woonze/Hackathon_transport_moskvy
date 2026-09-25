from __future__ import annotations

from datetime import date

import numpy as np

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


def _allocate_matrix(totals: np.ndarray, shares: list[float]) -> np.ndarray:
    """Allocate row totals by largest remainders, preserving every integer sum."""
    totals = np.asarray(totals, dtype=np.int64).reshape(-1)
    positive = np.maximum(np.asarray(shares, dtype=np.float64), 0)
    if not shares:
        return np.zeros((totals.size, 0), dtype=np.int64)
    share_total = positive.sum()
    if not totals.size or share_total <= 0:
        return np.zeros((totals.size, len(shares)), dtype=np.int64)

    exact = totals[:, None] * (positive / share_total)[None, :]
    allocated = np.floor(exact).astype(np.int64)
    remainder = totals - allocated.sum(axis=1)
    fractions = exact - allocated
    rows = np.arange(totals.size)[:, None]

    add_order = np.argsort(-fractions, axis=1, kind="stable")
    add_count = np.maximum(remainder, 0)
    if np.any(add_count):
        ranks = np.arange(len(shares))[None, :]
        allocated[rows, add_order] += ranks < add_count[:, None]

    # Floating point normalization can put an exact integer sum a few ulps over
    # the row total. Correct that rare case by removing units from the smallest
    # fractional parts, while keeping zero-share entries at zero.
    remove_count = np.maximum(-remainder, 0)
    if np.any(remove_count):
        remove_order = np.argsort(fractions, axis=1, kind="stable")
        for row in np.flatnonzero(remove_count):
            candidates = [i for i in remove_order[row] if allocated[row, i] > 0]
            for i in candidates[: int(remove_count[row])]:
                allocated[row, i] -= 1
    return allocated


def _grouped_stops(directions: dict[int, list[dict]]) -> tuple[list[str], dict[str, float], dict[str, list[dict]]]:
    records: dict[str, list[dict]] = {}
    for direction in sorted(directions):
        for stop in directions[direction]:
            records.setdefault(stop["stop_id"], []).append(stop)
    ids = sorted(records)
    shares = {stop_id: sum(stop["board_share"] for stop in records[stop_id]) for stop_id in ids}
    return ids, shares, records


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
    series.validate(store, kind.value, start, end, route, Granularity.day, limit_hours=False)
    _hours(hour_from, hour_to)
    flat = [s for d in sorted(directions) for s in directions[d]]
    stop_ids, stop_shares, records = _grouped_stops(directions)
    src = _source(store, kind)
    lo, hi = src.span(start, end)
    hourly = src.values[src.route_index[route], lo:hi, hour_from : hour_to + 1].reshape(-1)
    total = int(hourly.sum())
    by_stop = _allocate_matrix(hourly, [stop_shares[stop_id] for stop_id in stop_ids])
    record_totals = np.zeros(len(flat), dtype=np.int64)
    record_index = {id(stop): i for i, stop in enumerate(flat)}
    for column, stop_id in enumerate(stop_ids):
        indexes = [record_index[id(stop)] for stop in records[stop_id]]
        if len(indexes) == 1:
            record_totals[indexes[0]] = by_stop[:, column].sum()
            continue
        within_stop = _allocate_matrix(by_stop[:, column], [flat[i]["board_share"] for i in indexes])
        record_totals[indexes] = within_stop.sum(axis=0)
    stops = [
        {**_stop_dict(s), "boardings": count, "share": round(s["board_share"], 5)}
        for s, count in zip(flat, record_totals)
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
    routes = [r for r, dirs in store.stops.items() if (route is None or r == route) and any(
        s["stop_id"] == stop_id for stops in dirs.values() for s in stops
    )]
    if not routes:
        label = f" на маршруте {route}" if route is not None else ""
        raise ApiError(404, f"Остановка {stop_id}{label} не найдена", "stop_not_found")
    series.validate(store, kind.value, start, end, route, granularity)
    acc: dict[tuple, int] = {}
    src = _source(store, kind)
    lo, hi = src.span(start, end)
    dates = src.date_str[lo:hi]
    for route_id in routes:
        ids, shares, _ = _grouped_stops(store.stops[route_id])
        target_index = ids.index(stop_id)
        hourly = src.values[src.route_index[route_id], lo:hi].reshape(-1)
        allocations = _allocate_matrix(hourly, [shares[sid] for sid in ids])[:, target_index].reshape(-1, 24)
        for day_index, day in enumerate(dates):
            values = allocations[day_index]
            if granularity is Granularity.month:
                key = (day[:7],)
                acc[key] = acc.get(key, 0) + int(values.sum())
            elif granularity is Granularity.hour:
                for hour, passengers in enumerate(values):
                    key = (day, hour)
                    acc[key] = acc.get(key, 0) + int(passengers)
            else:
                key = (day,)
                acc[key] = acc.get(key, 0) + int(values.sum())
    names = ("month",) if granularity is Granularity.month else ("date", "hour") if granularity is Granularity.hour else ("date",)
    ref = next(s for dirs in store.stops.values() for d in dirs.values() for s in d if s["stop_id"] == stop_id)
    return {
        "estimated": True, "method": METHOD, "kind": kind.value, "stop_id": stop_id, "name": ref["name"],
        "routes": sorted(routes), "data": [dict(zip(names, key), passengers=v) for key, v in sorted(acc.items())],
    }
