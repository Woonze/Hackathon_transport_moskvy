from __future__ import annotations

import numpy as np

from ..errors import ApiError
from ..store import DataStore, Series
from . import series

CORRECTIONS = {"calendar", "regime", "weather"}


def parse(text: str | None) -> frozenset[str]:
    """Поправки из параметра запроса: «calendar,regime,weather»."""
    names = {t.strip() for t in (text or "").split(",") if t.strip()}
    bad = names - CORRECTIONS
    if bad:
        raise ApiError(422, f"Неизвестная поправка: {', '.join(sorted(bad))}. Допустимы: calendar, regime, weather", "unknown_correction")
    return frozenset(names)


def multiplier(store: DataStore, corrections: frozenset[str]) -> np.ndarray:
    """Куб множителей [маршрут, день, час] для выбранных поправок (по умолчанию единицы)."""
    fc, ext = store.forecast, store.external
    mult = np.ones(fc.values.shape)
    if "calendar" in corrections:
        if not ext.holidays:
            raise ApiError(422, "Производственный календарь недоступен: запустите python -m analysis.external_effects", "calendar_unavailable")
        # The trained model already uses day_type. Applying the measured holiday
        # factor again would double-count the same effect in scenario/export APIs.
        if not store.ml_status.get("calendar_in_model", False):
            for d in ext.holidays:
                lo, hi = fc.span(d, d)
                mult[:, lo:hi, :] *= ext.holiday_factor
    if "regime" in corrections:
        for cell in store.regime:
            ri = fc.route_index.get(cell["route"])
            if ri is not None:
                mult[ri, fc.weekday == cell["weekday"], :] *= cell["factor"]
    if "weather" in corrections:
        if not ext.weather:
            raise ApiError(422, "Данные о погоде недоступны: запустите python -m analysis.external_effects", "weather_unavailable")
        for i, day in enumerate(fc.dates):
            w = ext.weather.get(day.date())
            if w:
                mult[:, i, :] *= ext.weather_factor(w)
    return mult


def corrected_series(store: DataStore, corrections: frozenset[str]) -> Series:
    if not corrections:
        return store.forecast
    fc = store.forecast
    return series.cached(store, ("corrected", tuple(sorted(corrections))),
                         lambda: Series(fc.routes, fc.dates, np.rint(fc.values * multiplier(store, corrections)).astype(np.int64)))
