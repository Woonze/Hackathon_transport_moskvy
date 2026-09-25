"""Общая основа экспериментов по качеству прогноза: куб посадок [маршрут, день, час], календарь, погода, профили.

Все функции читают только данные до дня `a` (индекс первого прогнозного дня), поэтому годятся для скользящих бэктестов.
Модель model/forecast.py и submission.csv здесь не меняются.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analysis import external_effects as E

h = E.load_hourly()
ROUTES = sorted(int(r) for r in h.route.unique())
R = len(ROUTES)
DATES = pd.date_range("2025-01-01", "2025-10-31")
D = len(DATES)
Y = np.zeros((R, D, 24))
_ri, _di = {r: i for i, r in enumerate(ROUTES)}, {d: i for i, d in enumerate(DATES)}
for r, d, hh, y in zip(h.route, h.date, h.hour, h.y):
    Y[_ri[r], _di[d], hh] = y
CAL = E.load_calendar(False).set_index("date")
WX = E.load_weather(False).set_index("date")
DOW = DATES.dayofweek.to_numpy()
HOL = np.array([CAL.day_type.get(d) == "holiday" for d in DATES])
SUMMER = np.array([d.month in (6, 7, 8) for d in DATES])   # школьные каникулы: спрос ниже
FUT_N = 61


def score(y: np.ndarray, p: np.ndarray) -> float:
    return float(1 - np.abs(y - p).sum() / y.sum())


def best_scale(y: np.ndarray, p: np.ndarray) -> float:
    """Счёт при лучшем общем масштабе прогноза: убирает из сравнения ошибку уровня, оставляя структуру."""
    return max(score(y, p * g) for g in np.arange(0.7, 1.4, 0.005))


def fut_dates(a: int) -> pd.DatetimeIndex:
    return pd.date_range(DATES[0] + pd.Timedelta(days=a), periods=FUT_N)


def fut_dow(a: int) -> np.ndarray:
    return fut_dates(a).dayofweek.to_numpy()


def fut_hol(a: int) -> np.ndarray:
    return np.array([CAL.day_type.get(d) == "holiday" for d in fut_dates(a)]) & (fut_dow(a) < 5)


def anomaly_mask(a: int, lo: float = 0.6, hi: float = 1.6, win: int = 4) -> np.ndarray:
    """[R, a] True у маршрут-дней, сильно отличающихся от медианы соседних недель того же дня недели: ремонты, закрытия, объезды."""
    daily = Y[:, :a].sum(axis=2)
    mask = np.zeros((R, a), bool)
    for d in range(7):
        idx = np.flatnonzero((DOW[:a] == d) & ~HOL[:a])
        for r in range(R):
            v = daily[r, idx]
            for k in range(len(idx)):
                neigh = np.delete(v[max(0, k - win): k + win + 1], min(k, win))
                med = np.median(neigh) if len(neigh) else v[k]
                if med > 50 and (v[k] < lo * med or v[k] > hi * med):
                    mask[r, idx[k]] = True
    return mask


def _mean(x: np.ndarray, trim: float | None) -> np.ndarray:
    if not trim or len(x) - 2 * int(len(x) * trim) < 1:
        return x.mean(axis=0)
    k = int(len(x) * trim)
    return np.sort(x, axis=0)[k: len(x) - k].mean(axis=0)


def profile(a: int, mask: np.ndarray | None = None, days: np.ndarray | None = None, trim: float | None = None) -> np.ndarray:
    """[R, 7, 24] среднее (при trim: усечённое среднее) по маршрут × день недели × час; праздники и отмеченные `mask` маршрут-дни не участвуют."""
    prof = np.zeros((R, 7, 24))
    for d in range(7):
        m = (DOW[:a] == d) & ~HOL[:a]
        if days is not None:
            m &= days[:a]
        for r in range(R):
            mm = m & (~mask[r] if mask is not None else True)
            if mm.sum() == 0:
                mm = m
            prof[r, d] = _mean(Y[r, :a][mm], trim)
    return prof


def holiday_profile(a: int) -> np.ndarray | None:
    idx = np.flatnonzero(HOL[:a] & (DOW[:a] < 5))
    return Y[:, idx].mean(axis=1) if len(idx) else None


def predict_structured(a: int, season: bool = True, robust: bool = True, trim: float | None = None) -> np.ndarray:
    """Базовый вариант: профиль школьного сезона без аномальных маршрут-дней, отдельный профиль праздничных будней."""
    mask = anomaly_mask(a) if robust else np.zeros((R, a), bool)
    if season:
        mask = mask | SUMMER[:a][None, :]
    prof = profile(a, mask, trim=trim)
    dow = fut_dow(a)
    p = np.stack([prof[:, d] for d in dow], axis=1)
    hp = holiday_profile(a)
    if hp is not None:
        for i in np.flatnonzero(fut_hol(a)):
            p[:, i] = hp
    return p


STARTS = ["2025-03-01", "2025-03-15", "2025-04-01", "2025-04-15", "2025-05-01", "2025-05-15", "2025-06-01",
          "2025-06-15", "2025-07-01", "2025-07-15", "2025-08-01", "2025-08-15", "2025-09-01"]


def windows():
    """Окна «обучение до a → прогноз 61 день», как в задаче; последнее (1 сентября) совпадает с бэктестом команды."""
    for s in STARTS:
        a = _di[pd.Timestamp(s)]
        yield s, a, min(a + FUT_N, D)


def evaluate(predict, name: str, quiet: bool = False) -> tuple[float, float, float]:
    """Средний счёт по окнам, средний счёт при лучшем масштабе (без ошибки уровня), счёт окна сентябрь–октябрь."""
    sc, bs = [], []
    for _, a, b in windows():
        y, p = Y[:, a:b], predict(a)[:, : b - a]
        sc.append(score(y, p)); bs.append(best_scale(y, p))
    if not quiet:
        print(f"{name:<62}{np.mean(sc):>8.4f}{np.mean(bs):>10.4f}{sc[-1]:>10.4f}")
    return float(np.mean(sc)), float(np.mean(bs)), sc[-1]
