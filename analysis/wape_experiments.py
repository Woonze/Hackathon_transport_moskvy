"""Эксперименты по улучшению WAPE-score на нескольких отложенных окнах (модель и submission.csv не меняются).

    python -m analysis.wape_experiments

Окна имитируют реальную задачу: обучение до даты, прогноз на следующие ~2 месяца.
Постоянная калибровка 1,086 подобрана командой на сентябре–октябре, то есть на самом тесте, поэтому на этом окне она оптимистична.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analysis import external_effects as E

CALIB = 1.086
WINDOWS = [("Янв–апр → май–июнь", "2025-05-01", "2025-06-30"), ("Янв–июнь → июль–авг", "2025-07-01", "2025-08-31"), ("Янв–авг → сен–окт", "2025-09-01", "2025-10-31"), ("Янв–сен → октябрь", "2025-10-01", "2025-10-31")]
KEYS = ["route", "dow", "hour"]


def load() -> pd.DataFrame:
    cal, w, h = E.load_calendar(False), E.load_weather(False), E.load_hourly()
    h = h.merge(cal[["date", "day_type"]], on="date").merge(w, on="date")
    h["dow"] = h.date.dt.dayofweek
    h["is_hol"] = h.day_type == "holiday"
    return h


def holiday_factor(train: pd.DataFrame) -> float:
    d = train.groupby("date", as_index=False).agg(y=("y", "sum"), day_type=("day_type", "first"), precip=("precip", "first"), snow=("snow", "first"), tmean=("tmean", "first"))
    X, names = E.design(d)
    b, _ = E.ols(X, np.log(d.y.to_numpy()))
    return float(np.exp(b[names.index("holiday")])) if "holiday" in names else 1.0


def profile(train, clean=True, half=None, agg="mean") -> pd.DataFrame:
    d = train[~train.is_hol] if clean else train
    if agg == "median":
        return d.groupby(KEYS).y.median().rename("p").reset_index()
    if half:
        age = (train.date.max() - d.date).dt.days
        w = 0.5 ** (age / half)
        g = d.assign(yw=d.y * w, w=w).groupby(KEYS)[["yw", "w"]].sum()
        return (g.yw / g.w).rename("p").reset_index()
    return d.groupby(KEYS).y.mean().rename("p").reset_index()


def predict(train, test, prof, hol_factor=None, level=None, calib=CALIB):
    p = test.merge(prof, on=KEYS, how="left").p.fillna(0).to_numpy()
    if hol_factor is not None:
        p = np.where(test.is_hol.to_numpy(), p * hol_factor, p)
    if level == "global":
        recent = train[train.date > train.date.max() - pd.Timedelta(days=28)]
        pr = recent.merge(prof, on=KEYS, how="left").p.fillna(0)
        p = p * float(np.clip(recent.y.sum() / max(pr.sum(), 1), 0.8, 1.3))
    elif level == "route":
        recent = train[train.date > train.date.max() - pd.Timedelta(days=28)]
        pr = recent.merge(prof, on=KEYS, how="left")
        g = float(np.clip(recent.y.sum() / max(pr.p.fillna(0).sum(), 1), 0.8, 1.3))
        per = (pr.groupby("route").y.sum() / pr.groupby("route").p.sum().clip(lower=1)).clip(0.8, 1.3)
        f = (0.5 * per + 0.5 * g).reindex(test.route).fillna(g).to_numpy()
        p = p * f
    return p * calib


def regime_factors(train: pd.DataFrame, weeks: int = 6, lo: float = 0.7, hi: float = 1.3) -> pd.Series:
    """Маршрут × день недели: уровень последних `weeks` недель к среднему всей истории; учитываем только сильные сдвиги (вне [lo, hi]).

    Ловит структурные изменения (например, отмену выходных рейсов), которые усреднение по всей истории не видит.
    """
    daily = train[~train.is_hol].groupby(["route", "date"], as_index=False).y.sum()
    daily["dow"] = daily.date.dt.dayofweek
    cut = train.date.max() - pd.Timedelta(days=7 * weeks)
    allm = daily.groupby(["route", "dow"]).y.mean()
    rec = daily[daily.date > cut].groupby(["route", "dow"]).y.mean()
    f = (rec / allm).replace([np.inf, -np.inf], np.nan)
    return f.where((f < lo) | (f > hi))


def score(y, p):
    return max(0.0, 1 - np.abs(y - p).sum() / y.sum())


def main() -> None:
    h = load()
    variants = {}
    rows = []
    for title, a, b in WINDOWS:
        train, test = h[h.date < a], h[(h.date >= a) & (h.date <= b)]
        y, hf = test.y.to_numpy(), holiday_factor(train)
        if len(train) == 0: continue
        full = profile(train, clean=False)
        clean = profile(train)
        res = {
            "V0 Текущая модель (среднее по дню недели × 1,086)": predict(train, test, full),
            "V1 + поправка на праздничные будни": predict(train, test, full, hf),
            "V2 V1 без праздников в профиле": predict(train, test, clean, hf),
            "V3 V2 без константы 1,086 (калибровки нет)": predict(train, test, clean, hf, calib=1.0),
            "V4 V2 с уровнем последних 28 дней вместо 1,086": predict(train, test, clean, hf, level="global", calib=1.0),
            "V5 V4 по маршрутам (со сжатием к общему)": predict(train, test, clean, hf, level="route", calib=1.0),
            "V6 V4 + вес свежих данных (полураспад 60 дн.)": predict(train, test, profile(train, half=60), hf, level="global", calib=1.0),
            "V7 V4 + вес свежих данных (полураспад 30 дн.)": predict(train, test, profile(train, half=30), hf, level="global", calib=1.0),
            "V8 V4 с медианой вместо среднего": predict(train, test, profile(train, agg="median"), hf, level="global", calib=1.0),
        }
        rf = regime_factors(train)
        cell = test.set_index(["route", "dow"]).index.map(lambda k: rf.get(k, np.nan)).to_numpy(dtype=float)
        mult = np.where(np.isnan(cell), 1.0, cell)
        res["V9 V2 + поправка на структурные сдвиги (× 1,086)"] = res["V2 V1 без праздников в профиле"] * mult
        res["V10 V4 + поправка на структурные сдвиги"] = res["V4 V2 с уровнем последних 28 дней вместо 1,086"] * mult
        for name, p in res.items():
            variants.setdefault(name, []).append(round(score(y, p), 4))
    print(f"{'вариант':<52}" + "".join(f"{t:>22}" for t, _, _ in WINDOWS) + f"{'среднее':>10}")
    for name, sc in variants.items():
        print(f"{name:<52}" + "".join(f"{s:>22.4f}" for s in sc) + f"{np.mean(sc):>10.4f}")


def forecast_period() -> None:
    """Что дают варианты на самом прогнозном периоде (обучение по 31.10): суммы посадок и отличие от submission.csv."""
    h = load()
    hf = holiday_factor(h)
    fd = pd.date_range("2025-11-01", "2025-12-31")
    routes = sorted(h.route.unique())
    cal = E.load_calendar(False).set_index("date").day_type
    t = pd.MultiIndex.from_product([routes, fd, range(24)], names=["route", "date", "hour"]).to_frame(index=False)
    t["dow"] = t.date.dt.dayofweek
    t["is_hol"] = t.date.map(cal) == "holiday"
    sub = pd.read_csv("submission.csv", sep=";", parse_dates=["date"])
    base = sub.prediction.sum()
    recent = h[h.date > h.date.max() - pd.Timedelta(days=28)]
    prof = profile(h)
    pr = recent.merge(prof, on=KEYS, how="left").p.fillna(0).sum()
    print(f"\nУровень октября (последние 28 дней) к чистому профилю: ×{recent.y.sum() / pr:.3f} (у текущей модели константа ×{CALIB})")
    for name, p in [("Текущая модель (submission.csv)", None), ("Чистый профиль + праздники, × 1,086", predict(h, t, prof, hf)),
                    ("Чистый профиль + праздники, уровень октября", predict(h, t, prof, hf, level="global", calib=1.0))]:
        tot = base if p is None else p.sum()
        print(f"{name:<52}{tot:>14,.0f} посадок за 2 месяца  {(tot / base - 1) * 100:+6.1f}% к submission")
    rf = regime_factors(h)
    flagged = rf.dropna()
    print("\nЯчейки со структурным сдвигом (свежие 6 недель к средней за всю историю):")
    for (r, d), v in flagged.items():
        print(f"  маршрут {r}, {['пн','вт','ср','чт','пт','сб','вс'][d]}: ×{v:.2f}")
    cell = t.set_index(["route", "dow"]).index.map(lambda k: rf.get(k, np.nan)).to_numpy(dtype=float)
    mult = np.where(np.isnan(cell), 1.0, cell)
    p_all = predict(h, t, prof, hf) * mult
    print(f"Изменение прогноза при поправке на сдвиги: {(p_all.sum() / predict(h, t, prof, hf).sum() - 1) * 100:+.1f}% от суммы посадок; доля submission: {(p_all.sum() / base - 1) * 100:+.1f}%")
    for m in (11, 12):
        s_m = sub[sub.date.dt.month == m].prediction.sum()
        o = h[h.date.dt.month == 10].y.sum()
        print(f"  submission: {m}-й месяц {s_m:,.0f}; к октябрю факт {o:,.0f}: {(s_m / o - 1) * 100:+.1f}% ({'30' if m == 11 else '31'} дн. против 31)")


if __name__ == "__main__":
    main()
    forecast_period()
