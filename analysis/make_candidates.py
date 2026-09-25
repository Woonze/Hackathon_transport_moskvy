"""Набор кандидатов на загрузку: submission.csv + измеренные поправки (модель и submission.csv не меняются).

    python -m analysis.make_candidates      → artifacts/candidates/*.csv и candidates_index.csv

Поправки:
  H — праздничные будни 3.11, 4.11, 31.12 умножаются на коэффициент (эффект измерен по истории 2025, analysis/external_effects.py);
  R — структурные сдвиги «маршрут × день недели»: маршрут 50 в сб и вс, маршрут 7 в вс (свежие 6 недель против всей истории,
      analysis/wape_experiments.regime_factors);
  S — общий множитель уровня (в submission.csv уже заложена константа 1,086; S < 1 приближает уровень к октябрю).
Платформа даёт до 24 успешных попыток в сутки, в зачёт идёт лучший скор: кандидаты предназначены для проверки скором платформы.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analysis import external_effects as E
from analysis import wape_experiments as W

ROOT = E.ROOT
OUT = ROOT / "artifacts" / "candidates"


def build(sub: pd.DataFrame, hol_dates, hol: float | None, regime: pd.Series | None, scale: float, regime_routes=None) -> pd.DataFrame:
    p = sub.prediction.to_numpy(dtype=float) * scale
    if hol is not None:
        p = np.where(sub.date.isin(hol_dates), p * hol, p)
    if regime is not None:
        dow = sub.date.dt.dayofweek
        f = np.array([regime.get((r, d), np.nan) for r, d in zip(sub.route, dow)], dtype=float)
        if regime_routes is not None:
            f = np.where(sub.route.isin(regime_routes), f, np.nan)
        p = p * np.where(np.isnan(f), 1.0, f)
    out = sub.copy()
    out["prediction"] = np.maximum(np.rint(p), 0).astype(int)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sub = pd.read_csv(ROOT / "submission.csv", sep=";", parse_dates=["date"])
    h = W.load()
    cal = E.load_calendar(False)
    hol_dates = set(cal[(cal.day_type == "holiday") & (cal.date >= "2025-11-01") & (cal.date <= "2025-12-31")].date)
    h_pooled = W.holiday_factor(h)
    h_spring = 0.506  # весенние праздники (1–2, 8–9 мая, 12–13 июня): −49,4 %
    regime = W.regime_factors(h).dropna()
    base = sub.prediction.sum()
    specs = [
        ("c01_H", "только праздники (объединённая оценка −53,5 %)", dict(hol=h_pooled, regime=None, scale=1.0)),
        ("c02_H_R", "праздники + сдвиги (маршрут 50 сб, вс; маршрут 7 вс)", dict(hol=h_pooled, regime=regime, scale=1.0)),
        ("c03_H_R50", "праздники + сдвиг только маршрута 50", dict(hol=h_pooled, regime=regime, scale=1.0, regime_routes=[50])),
        ("c04_Hspring_R", "праздники по весенней оценке (−49,4 %) + сдвиги", dict(hol=h_spring, regime=regime, scale=1.0)),
        ("c05_H_R_s098", "c02 с уровнем ×0,98", dict(hol=h_pooled, regime=regime, scale=0.98)),
        ("c06_H_R_s096", "c02 с уровнем ×0,96 (ближе к октябрю)", dict(hol=h_pooled, regime=regime, scale=0.96)),
        ("c07_H_R_s094", "c02 с уровнем ×0,94", dict(hol=h_pooled, regime=regime, scale=0.94)),
        ("c08_H_R_s102", "c02 с уровнем ×1,02", dict(hol=h_pooled, regime=regime, scale=1.02)),
        ("c09_R", "только сдвиги, без праздников", dict(hol=None, regime=regime, scale=1.0)),
    ]
    index = []
    for name, desc, kw in specs:
        c = build(sub, hol_dates, **kw)
        assert len(c) == 14640 and c.prediction.min() >= 0 and not c.prediction.isna().any()
        c_out = c.assign(date=c.date.dt.strftime("%Y-%m-%d"))
        c_out.to_csv(OUT / f"{name}.csv", sep=";", index=False)
        index.append({"файл": f"{name}.csv", "описание": desc, "сумма посадок": int(c.prediction.sum()), "к submission.csv, %": round((c.prediction.sum() / base - 1) * 100, 2)})
    idx = pd.DataFrame(index)
    idx.to_csv(OUT / "candidates_index.csv", sep=";", index=False)
    print(f"Праздничные дни: {sorted(d.strftime('%d.%m') for d in hol_dates)}; коэффициент {h_pooled:.3f} (весенний {h_spring})")
    print("Сдвиги:", {f"маршрут {r}, {['пн','вт','ср','чт','пт','сб','вс'][d]}": round(v, 3) for (r, d), v in regime.items()})
    print(idx.to_string(index=False))


if __name__ == "__main__":
    main()
