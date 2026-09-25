"""Проверка гипотез о том, что улучшает прогноз: 13 скользящих окон «обучение до даты → прогноз 61 день».

    python -m analysis.hypotheses

Колонки: средний WAPE-score по окнам, то же при лучшем общем масштабе (ошибка уровня убрана, остаётся структура),
счёт окна «январь–август → сентябрь–октябрь» (тот же бэктест, что у model/forecast.py).
Модель и submission.csv не меняются. Градиентный бустинг подключается, если установлен scikit-learn.
"""
from __future__ import annotations

import numpy as np

from analysis import panel as P
from analysis.panel import D, DATES, FUT_N, HOL, R, ROUTES, SUMMER, Y, fut_dates, fut_dow, fut_hol, score
from backend.app.console import configure_console

CALIB = 1.086
HEAD = f"{'гипотеза':<62}{'среднее':>8}{'лучш.масшт.':>10}{'сен–окт':>10}"


def profile_plain(a, calib=1.0):
    """как model/forecast.py: среднее по маршрут × день недели × час за всю историю, без исключений"""
    prof = np.stack([Y[:, :a][:, P.DOW[:a] == d].mean(axis=1) for d in range(7)], axis=1)
    return np.stack([prof[:, d] for d in fut_dow(a)], axis=1) * calib


def with_regime(a, base, weeks=6, lo=0.7, hi=1.3):
    """автоматическая поправка на сдвиги режима: свежие `weeks` недель к средней за нормальные дни"""
    daily = Y[:, :a].sum(axis=2)
    m = np.ones((R, 7))
    for d in range(7):
        allm = (P.DOW[:a] == d) & ~HOL[:a]
        rec = allm & (np.arange(a) >= a - 7 * weeks)
        if rec.sum() < 3 or allm.sum() < 12:
            continue
        f = daily[:, rec].mean(axis=1) / np.maximum(daily[:, allm].mean(axis=1), 1)
        m[:, d] = np.where((f < lo) | (f > hi), f, 1.0)
    return base * np.stack([m[:, d] for d in fut_dow(a)], axis=1)[:, :, None]


def with_weather(a, base, kind):
    """регрессия лог-отношения суточного факта к профилю на погоду по обучающим дням, множитель на прогнозные дни (по фактической погоде)"""
    wx = P.WX.reindex(P.pd.date_range("2025-01-01", "2025-12-31"))

    def feats(dates):
        t, cols = wx.loc[dates], []
        if "rain" in kind: cols.append((t.precip >= 5).astype(float))
        if "snow" in kind: cols.append((t.snow >= 2).astype(float))
        if "precip" in kind: cols.append(np.log1p(t.precip.fillna(0)))
        if "temp" in kind: cols.append((t.tmean.fillna(8) - 8) / 10)
        return np.column_stack([c.to_numpy() for c in cols])

    mask = P.anomaly_mask(a) | SUMMER[:a][None, :]
    prof = P.profile(a, mask)
    idx = np.flatnonzero(~HOL[:a])
    z = np.log(np.maximum(Y[:, idx].sum(axis=(0, 2)), 1) / np.maximum(np.stack([prof[:, P.DOW[i]] for i in idx], axis=1).sum(axis=(0, 2)), 1))
    X = np.c_[np.ones(len(idx)), feats(DATES[idx])]
    coef = np.linalg.solve(X.T @ X + np.diag([0] + [1] * (X.shape[1] - 1)), X.T @ z)
    mult = np.exp(np.c_[np.ones(FUT_N), feats(fut_dates(a))] @ coef - coef[0])
    return base * mult[None, :, None]


def with_level(a, base, K=28, shrink=0.5, lo=0.85, hi=1.15):
    """уровень маршрута по последним K «нормальным» дням (без праздников, лета и аномалий), со сжатием к общему уровню сети"""
    mask = P.anomaly_mask(a) | SUMMER[:a][None, :]
    prof = P.profile(a, mask)
    idx = np.flatnonzero(~HOL[:a] & ~SUMMER[:a])[-K:]
    pr = np.stack([prof[:, P.DOW[i]] for i in idx], axis=1)
    good = ~mask[:, idx]
    num, den = (Y[:, idx].sum(axis=2) * good).sum(axis=1), (pr.sum(axis=2) * good).sum(axis=1)
    per = np.clip(num / np.maximum(den, 1), lo, hi)
    g = np.clip(num.sum() / max(den.sum(), 1), lo, hi)
    return base * (shrink * per + (1 - shrink) * g)[:, None, None]


def oracle_report():
    """Потолки: что было бы при идеальном знании средних окна (профиль окна) и при известных суточных суммах."""
    print("\nПотолки на окне сентябрь–октябрь (в выборке, т. е. недостижимо в прогнозе):")
    a, b = P._di[P.pd.Timestamp("2025-09-01")], D
    y, dow, hol = Y[:, a:b], P.DOW[a:b], HOL[a:b]
    prof = np.zeros_like(y)
    for d in range(7):
        m = (dow == d) & ~hol
        prof[:, dow == d] = y[:, m].mean(axis=1)[:, None, :]
    day_tot, pt = y.sum(axis=2, keepdims=True), prof.sum(axis=2, keepdims=True)
    print(f"  профиль самого окна (точные средние маршрут × день недели × час): {score(y, prof):.4f}")
    print(f"  + известны суточные суммы каждого маршрута:                        {score(y, np.where(pt > 0, prof / np.maximum(pt, 1e-9), 0) * day_tot):.4f}")
    mu = prof
    print(f"  чистый пуассоновский шум при точном среднем (нижняя граница ошибки): {1 - np.sqrt(2 * np.maximum(mu, 0) / np.pi).sum() / y.sum():.4f}")


def informed_regime_gain():
    """Что дало бы заранее известное изменение режима: маршрут 50 без выходных и маршрут 7 короче по выходным с 6 сентября (ремонт путей)."""
    a, b = P._di[P.pd.Timestamp("2025-09-01")], D
    p, y = P.predict_structured(a)[:, : b - a], Y[:, a:b]
    q, wk = p.copy(), np.isin(fut_dow(a)[: b - a], (5, 6))
    for route in (50, 7):
        r = ROUTES.index(route)
        q[r][wk] = p[r][wk] * (y[r][wk].sum() / p[r][wk].sum())
    print(f"\nОкно сентябрь–октябрь: {score(y, p):.4f} → {score(y, q):.4f} (+{(score(y, q) - score(y, p)) * 100:.2f} п.п.), если режим маршрутов 7 и 50 по выходным известен заранее")


def main() -> None:
    print(HEAD)
    print("— исходная модель и календарь —")
    P.evaluate(lambda a: profile_plain(a, CALIB), "Текущая модель: среднее по дню недели × 1,086")
    P.evaluate(lambda a: profile_plain(a), "  то же без константы 1,086")
    P.evaluate(lambda a: P.predict_structured(a, season=False, robust=False), "+ праздничные будни отдельным профилем, профиль без праздников")
    print("— исключения из профиля —")
    P.evaluate(lambda a: P.predict_structured(a, season=False), "+ без аномальных маршрут-дней (ремонты, закрытия)")
    P.evaluate(lambda a: P.predict_structured(a, season=True, robust=False), "+ без летних каникул (июнь–август), без исключения аномалий")
    P.evaluate(lambda a: P.predict_structured(a), "+ оба исключения (базовый вариант нового подхода)")
    print("— сдвиги режима: автоматическое определение по свежим неделям —")
    for w, lo, hi in ((6, 0.7, 1.3), (8, 0.7, 1.3), (4, 0.7, 1.3), (12, 0.8, 1.2)):
        P.evaluate(lambda a: with_regime(a, P.predict_structured(a), w, lo, hi), f"базовый + режим за {w} нед., порог {lo}–{hi}")
    print("— погода (по фактическим данным Open-Meteo) —")
    for kind in (("rain",), ("rain", "snow"), ("precip",), ("temp",), ("rain", "snow", "temp")):
        P.evaluate(lambda a, k=kind: with_weather(a, P.predict_structured(a), k), "базовый + погода: " + ", ".join(kind))
    try:
        from sklearn.ensemble import HistGradientBoostingRegressor  # noqa: F401
        from analysis import gbm
        print("— градиентный бустинг (Пуассон, календарь и признаки дня) —")
        P.evaluate(lambda a: gbm.predict(a, ("summer",)), "GBM: маршрут, день недели, час, календарь, лето")
        P.evaluate(lambda a: gbm.predict(a, ("summer", "wx")), "GBM + погода")
        P.evaluate(lambda a: 0.5 * gbm.predict(a, ("summer",)) + 0.5 * P.predict_structured(a), "смесь 50/50 GBM и базового профиля")
    except ImportError:
        print("(scikit-learn не установлен: градиентный бустинг пропущен)")
    print("— уровень маршрута по последним неделям вместо калибровки —")
    for k in (28, 56, 84):
        P.evaluate(lambda a, k=k: with_level(a, P.predict_structured(a), k), f"базовый + уровень маршрута по последним {k} нормальным дням")
    oracle_report()
    informed_regime_gain()


if __name__ == "__main__":
    configure_console()
    main()
