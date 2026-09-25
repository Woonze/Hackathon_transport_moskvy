from __future__ import annotations

import math
from datetime import date

import numpy as np

from ..errors import ApiError
from ..schemas import Granularity, Kind
from ..store import DataStore
from . import corrections as corr, series, stops

HIGH, LOW = 1.15, 0.85  # индекс часа к обычному дню: выше или ниже этих порогов час считается отклонившимся
PEAK_HOURS = 3
DEFAULT_CORRECTIONS = "calendar,regime"
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
METHOD = (
    "Спрос по часам берётся из прогноза с выбранными поправками. «Обычный день» это среднее по тем же дням недели за ноябрь–декабрь без праздников. "
    "Пиковые часы — три часа с наибольшими посадками. Горячие участки — оценка (посадки маршрута распределены по остановкам справочника). "
    "Расчёт вагонов использует пропускную способность вагона, которую задаёт пользователь: в справочнике вместимость есть только классом (ОБК, БК), числа нет."
)


def _level(boardings: int, typical: float, peak: bool) -> tuple[float | None, str]:
    if typical <= 0 and boardings == 0:
        return None, "нет движения"
    idx = boardings / typical if typical > 0 else None
    if peak:
        return idx, "пик"
    if idx is None or idx >= HIGH:
        return idx, "выше обычного"
    return idx, "ниже обычного" if idx <= LOW else "обычно"


def day_plan(store: DataStore, route: int | None, day: date, correction_names: str | None, capacity: float | None, vehicles: int | None) -> dict:
    series.validate(store, "forecast", day, day, route, Granularity.day, limit_hours=False)
    names = corr.parse(correction_names)
    if (capacity is None) != (vehicles is None):
        raise ApiError(422, "Для расчёта вагонов нужны оба параметра: capacity и vehicles", "capacity_and_vehicles")
    if capacity is not None and route is None:
        raise ApiError(422, "Расчёт вагонов возможен только для одного маршрута: укажите route", "vehicles_need_route")
    cube = corr.corrected_series(store, names)
    ris = series.resolve_route(store, route)
    di = cube.span(day, day)[0]
    hourly = cube.values[ris, di, :].sum(axis=0).astype(np.int64)
    base_hourly = store.forecast.values[ris, di, :].sum(axis=0)

    holidays = np.array([d.date() in store.external.holidays for d in cube.dates])
    same = (cube.weekday == cube.weekday[di]) & ~holidays
    same[di] = False
    typical = cube.values[np.ix_(ris, np.flatnonzero(same))].sum(axis=0).mean(axis=0) if same.any() else np.zeros(24)

    total = int(hourly.sum())
    top = set(np.argsort(-hourly)[:PEAK_HOURS].tolist()) if total else set()
    active = hourly[hourly >= max(1, total * 0.01)]
    rows = []
    for h in range(24):
        idx, level = _level(int(hourly[h]), float(typical[h]), h in top and hourly[h] > 0)
        rows.append({"hour": h, "boardings": int(hourly[h]), "share": round(hourly[h] / total, 4) if total else 0.0,
                     "typical": round(float(typical[h])), "index": round(idx, 3) if idx is not None else None, "level": level})
    if capacity is not None:
        for r in rows:
            need = math.ceil(r["boardings"] / capacity) if r["boardings"] else 0
            load = r["boardings"] / (vehicles * capacity)
            r.update({"load": round(load, 3), "vehicles_needed": need, "vehicles_delta": need - vehicles,
                      "load_level": "перегрузка" if load > 1 else "запас" if load < 0.5 else "норма"})
    out = {
        "date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()], "route": route, "corrections": sorted(names), "day_total": total,
        "hours": rows,
        "peaks": {"hours": sorted(top), "share": round(float(hourly[list(top)].sum() / total), 4) if total else 0.0,
                  "peak_to_mean": round(float(hourly.max() / active.mean()), 2) if len(active) else None},
        "hotspots": _hotspots(store, route, day, hourly, base_hourly),
        "estimated": True, "method": METHOD,
    }
    if capacity is not None:
        out["vehicles"] = {"capacity_per_vehicle_hour": capacity, "vehicles": vehicles,
                           "overloaded_hours": [r["hour"] for r in rows if r["load_level"] == "перегрузка"]}
    return out


def _hotspots(store: DataStore, route: int | None, day: date, hourly: np.ndarray, base_hourly: np.ndarray) -> list[dict] | None:
    """Самый загруженный участок в каждый час (оценка), пять самых нагруженных."""
    if route is None or route not in store.stops:
        return None
    found = []
    for h in range(24):
        if hourly[h] <= 0 or base_hourly[h] <= 0:
            continue
        peak = stops.segments(store, Kind.forecast, route, day, day, h, h)["peak"]
        if peak:  # участки считаются по прогнозу без поправок, приводим к выбранным поправкам
            found.append({"hour": h, "direction": peak["direction"], "from": peak["from"]["name"], "to": peak["to"]["name"],
                          "passengers": round(peak["passengers"] * hourly[h] / base_hourly[h])})
    return sorted(found, key=lambda x: -x["passengers"])[:5]


def savings(store: DataStore, route: int | None, correction_names: str | None, threshold: float, limit: int) -> dict:
    names = corr.parse(correction_names)
    ris = series.resolve_route(store, route)
    fc, cube = store.forecast, corr.corrected_series(store, names)
    base = fc.values[ris].sum(axis=2)
    adj = cube.values[ris].sum(axis=2)
    holidays = store.external.holidays
    cells = {(c["route"], c["weekday"]) for c in store.regime} if "regime" in names else set()
    days = []
    for a, ri in enumerate(ris):
        for d in np.flatnonzero((base[a] > 0) & (adj[a] <= base[a] * (1 - threshold))):
            dt = fc.dates[d]
            reasons = []
            if "calendar" in names and dt.date() in holidays:
                reasons.append("праздничный день")
            if (fc.routes[ri], dt.weekday()) in cells:
                reasons.append("сдвиг режима маршрута")
            days.append({"route": fc.routes[ri], "date": dt.date().isoformat(), "weekday": WEEKDAYS[dt.weekday()], "base": int(base[a, d]),
                         "corrected": int(adj[a, d]), "delta": int(base[a, d] - adj[a, d]), "reasons": reasons or ["поправка погоды или иная"]})
    days.sort(key=lambda x: -x["delta"])
    delta = sum(x["delta"] for x in days)
    return {"corrections": sorted(names), "threshold": threshold, "route": route, "total_days": len(days), "total_delta": delta,
            "share_of_forecast": round(delta / int(base.sum()), 4) if base.sum() else 0.0, "days": days[:limit],
            "note": "Дни, где прогноз с поправками ниже прогноза модели на threshold и более: возможен пересмотр выпуска. Оценка по прогнозу, не измеренная экономия."}
