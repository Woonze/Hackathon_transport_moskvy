from __future__ import annotations

import numpy as np

from .. import config

WEEKS = 6               # окно «свежих» недель
LOW, HIGH = 0.7, 1.3    # сдвиг считается структурным, если уровень вышел за эти границы
MIN_RECENT, MIN_ALL = 4, 20
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
METHOD = (
    f"Для каждой пары «маршрут × день недели» сравнивается средняя суточная посадка за последние {WEEKS} недель истории "
    f"со средней за всю историю (праздничные будни не учитываются). Если уровень ниже ×{LOW} или выше ×{HIGH}, "
    "это считается структурным сдвигом (например, отмена выходных рейсов), который усреднение по всей истории не видит."
)


def compute(history, calendar: dict) -> list[dict]:
    """Структурные сдвиги режима по истории (разметка и принятые данные внутри периода истории)."""
    lo, hi = history.span(config.HISTORY_START, config.HISTORY_END)
    dates = history.dates[lo:hi]
    daily = history.values[:, lo:hi].sum(axis=2)
    dow = dates.dayofweek.to_numpy()
    holiday = np.array([calendar.get(d.date()) == "holiday" for d in dates])
    recent = np.arange(len(dates)) >= len(dates) - 7 * WEEKS
    cells = []
    for ri, route in enumerate(history.routes):
        for d in range(7):
            all_days = (dow == d) & ~holiday
            recent_days = all_days & recent
            if recent_days.sum() < MIN_RECENT or all_days.sum() < MIN_ALL:
                continue
            hist_mean, recent_mean = float(daily[ri][all_days].mean()), float(daily[ri][recent_days].mean())
            if hist_mean <= 0:
                continue
            factor = recent_mean / hist_mean
            if LOW <= factor <= HIGH:
                continue
            cells.append({"route": int(route), "weekday": d, "weekday_name": WEEKDAYS[d], "factor": round(factor, 4),
                          "recent_mean": round(recent_mean), "history_mean": round(hist_mean)})
    return cells
