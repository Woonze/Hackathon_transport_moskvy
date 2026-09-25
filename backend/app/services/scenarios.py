from __future__ import annotations

import calendar

import numpy as np

from .. import config
from ..errors import ApiError
from ..schemas import AdjustRequest, Granularity
from ..store import Series
from . import corrections as corr
from . import series

def adjusted(store, req: AdjustRequest) -> dict:
    fc = store.forecast
    series.validate(store, "forecast", req.start, req.end, req.route, req.granularity)

    ext = store.external
    names = frozenset(n for n, on in (("calendar", req.calendar), ("regime", req.regime), ("weather", req.weather_auto)) if on)
    mult = np.full(fc.values.shape, req.factors.weather * req.factors.event * req.factors.season) * corr.multiplier(store, names)
    for rule in req.rules:
        if rule.end < config.FORECAST_START or rule.start > config.FORECAST_END:
            raise ApiError(422, f"Правило вне периода прогноза {config.FORECAST_START} — {config.FORECAST_END}", "rule_out_of_range")
        ris = [fc.route_index[r] if r in fc.route_index else _unknown(store, r) for r in rule.routes] if rule.routes else slice(None)
        lo, hi = fc.span(rule.start, rule.end)
        mult[ris, lo:hi, rule.hour_from : rule.hour_to + 1] *= rule.factor

    tmp = Series(fc.routes, fc.dates, np.rint(fc.values * mult).astype(np.int64))
    new = series.rows(store, tmp, req.start, req.end, req.route, req.granularity)
    base = series.rows(store, fc, req.start, req.end, req.route, req.granularity)
    for n, b in zip(new, base):
        n["base"] = b["passengers"]
    total_base = sum(b["passengers"] for b in base)
    total_new = sum(n["passengers"] for n in new)
    return {
        "summary": {
            "base_total": total_base,
            "adjusted_total": total_new,
            "delta": total_new - total_base,
            "delta_pct": round((total_new / total_base - 1) * 100, 2) if total_base else None,
            "global_multiplier": round(req.factors.weather * req.factors.event * req.factors.season, 4),
            "rules_applied": len(req.rules),
            "calendar_days": [d.isoformat() for d in ext.holidays] if req.calendar else [],
            "regime_cells": [{"route": c["route"], "weekday": c["weekday_name"], "factor": c["factor"]} for c in store.regime if req.route in (None, c["route"])] if req.regime else [],
            "weather_days": [d["date"] for d in _weather_hits(store)] if req.weather_auto else [],
        },
        "data": new,
    }


def _unknown(store, route: int):
    raise ApiError(404, f"Маршрут {route} из правила не найден. Доступны: {', '.join(map(str, store.routes))}", "route_not_found")


def year_outlook(store, route: int | None, growth: float) -> dict:
    """2025: 10 месяцев факта + 2 месяца прогноза. 2026: сезонный профиль 2025 без тренда × growth."""
    series.resolve_route(store, route)
    fact = series.rows(store, store.history, config.HISTORY_START, config.HISTORY_END, route, Granularity.month)
    pred = series.rows(store, store.forecast, config.FORECAST_START, config.FORECAST_END, route, Granularity.month)
    months = [{**r, "source": "fact"} for r in fact] + [{**r, "source": "forecast"} for r in pred]
    scenario = []
    for r in months:
        year, month = map(int, r["month"].split("-"))
        per_day = r["passengers"] / calendar.monthrange(year, month)[1]
        days = calendar.monthrange(year + 1, month)[1]
        scenario.append({"route": r["route"], "month": f"{year + 1}-{month:02d}", "passengers": int(round(per_day * days * growth)), "source": "scenario"})
    return {
        "note": (
            "2025: январь–октябрь — факт, ноябрь–декабрь — прогноз модели. 2026: сценарная оценка — "
            "сезонный профиль 2025 без учёта тренда, пересчитанный на число дней месяца и умноженный на growth. "
            "Это не прогноз модели: данных за полный год для обучения нет."
        ),
        "growth": growth,
        "data": months + scenario,
    }


def _weather_hits(store) -> list[dict]:
    from . import external
    return [d for d in external.weather_days(store.external, config.FORECAST_START, config.FORECAST_END) if d["factor"] != 1.0]
