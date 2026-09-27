"""Внешние источники (производственный календарь РФ, погода Москвы) → измеренный эффект на посадках.

    python -m analysis.external_effects            # скачать (или взять из кэша) и пересчитать
    python -m analysis.external_effects --refresh  # перекачать источники

Источники:
  * календарь — https://isdayoff.ru (API производственного календаря РФ: 0 рабочий, 1 выходной/праздник, 2 сокращённый)
  * погода    — https://open-meteo.com (архив ERA5, Москва 55.75 N 37.62 E)
Результаты: artifacts/external/{calendar,weather}_2025.csv и effects.json (его читает сервис для /factors и /calendar).
Модель model/forecast.py и submission.csv скрипт не меняет: сравнение — эксперимент; в artifacts/submission_calendar_proposal.csv
кладётся предложение (только праздничные будни умножены на измеренный коэффициент), решение о переносе остаётся за ML-участником.
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from backend.app.console import configure_console
from model.forecast import CALIBRATION

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "artifacts" / "external"
LABELS = [ROOT / "dataset" / "labels" / "labels_day_train.csv", ROOT / "dataset" / "labels" / "labels_day_test.csv"]
CAL_URL = "https://isdayoff.ru/api/getdata?year=2025&pre=1&cc=ru"
WEATHER_URL = (
    "https://archive-api.open-meteo.com/v1/archive?latitude=55.75&longitude=37.62&start_date=2025-01-01&end_date=2025-12-31"
    "&daily=temperature_2m_mean,precipitation_sum,snowfall_sum&timezone=Europe%2FMoscow"
)


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read().decode("utf-8")


def load_calendar(refresh: bool) -> pd.DataFrame:
    path = EXT / "calendar_2025.csv"
    if refresh or not path.exists():
        codes = fetch(CAL_URL).strip()
        days = pd.date_range("2025-01-01", periods=len(codes), freq="D")
        pd.DataFrame({"date": days.strftime("%Y-%m-%d"), "code": [int(c) for c in codes]}).to_csv(path, index=False)
    df = pd.read_csv(path, parse_dates=["date"], usecols=["date", "code"])
    dow = df["date"].dt.dayofweek
    # holiday — выходной в будни (праздник/перенос), weekend — обычные сб/вс, short — сокращённый день
    df["day_type"] = np.select(
        [(df.code == 1) & (dow < 5), df.code == 1, (df.code == 2), (dow >= 5)],
        ["holiday", "weekend", "short", "work_weekend"], default="work",
    )
    df.assign(date=df.date.dt.strftime("%Y-%m-%d")).to_csv(path, index=False)
    return df


def load_weather(refresh: bool) -> pd.DataFrame:
    path = EXT / "weather_2025.csv"
    if refresh or not path.exists():
        d = json.loads(fetch(WEATHER_URL))["daily"]
        pd.DataFrame({"date": d["time"], "tmean": d["temperature_2m_mean"], "precip": d["precipitation_sum"], "snow": d["snowfall_sum"]}).to_csv(path, index=False)
    return pd.read_csv(path, parse_dates=["date"])


def load_hourly() -> pd.DataFrame:
    h = pd.concat([pd.read_csv(p, sep=";") for p in LABELS], ignore_index=True)
    h["date"] = pd.to_datetime(h["date"])
    routes = sorted(h.route.unique())
    idx = pd.MultiIndex.from_product([routes, pd.date_range(h.date.min(), h.date.max()), range(24)], names=["route", "date", "hour"])
    return h.set_index(["route", "date", "hour"]).boardings.reindex(idx, fill_value=0).rename("y").reset_index()


def ols(X: np.ndarray, y: np.ndarray):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = len(y) - X.shape[1]
    cov = resid @ resid / dof * np.linalg.pinv(X.T @ X)
    return beta, np.sqrt(np.diag(cov))


def design(days: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    d = days
    cols = {"const": np.ones(len(d))}
    for k in range(1, 7):
        cols[f"dow{k}"] = (d.date.dt.dayofweek == k).astype(float).to_numpy()
    for m in range(2, 13):
        if (d.date.dt.month == m).any():
            cols[f"month{m}"] = (d.date.dt.month == m).astype(float).to_numpy()
    cols["holiday"] = (d.day_type == "holiday").astype(float).to_numpy()
    cols["work_weekend"] = (d.day_type == "work_weekend").astype(float).to_numpy()
    cols["short"] = (d.day_type == "short").astype(float).to_numpy()
    cols["rain"] = (d.precip >= 5).astype(float).to_numpy()
    cols["snow"] = (d.snow >= 2).astype(float).to_numpy()
    cols["cold"] = (d.tmean <= -10).astype(float).to_numpy()
    cols["hot"] = (d.tmean >= 25).astype(float).to_numpy()
    cols = {k: v for k, v in cols.items() if k == "const" or v.sum() > 0}  # признак, которого нет в данных, не оценить
    return np.column_stack(list(cols.values())), list(cols)


def day_class(day_type: pd.Series, dow: pd.Series) -> pd.Series:
    """Профильный класс дня: рабочий / суббота / воскресенье-праздник."""
    off = day_type.isin(["weekend", "holiday"])
    return np.select([off & (dow == 5), off], ["sat", "off"], default="work")


def predict(train: pd.DataFrame, target: pd.DataFrame, key: str) -> np.ndarray:
    prof = train.groupby(["route", key, "hour"], as_index=False).y.mean().rename(columns={"y": "p"})
    return target.merge(prof, on=["route", key, "hour"], how="left").p.fillna(0).to_numpy()


def score(y: np.ndarray, p: np.ndarray) -> float:
    return max(0.0, 1 - np.abs(y - p).sum() / y.sum())


def best_scale(y: np.ndarray, p: np.ndarray) -> float:
    return max(np.linspace(0.8, 1.4, 121), key=lambda c: score(y, p * c))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    EXT.mkdir(parents=True, exist_ok=True)

    cal, weather, hourly = load_calendar(args.refresh), load_weather(args.refresh), load_hourly()
    hourly = hourly.merge(cal[["date", "day_type"]], on="date").merge(weather, on="date")
    hourly["dow"] = hourly.date.dt.dayofweek
    hourly["weekday_key"] = hourly.dow.astype(str)
    hourly["dow_hol_key"] = np.where(hourly.day_type == "holiday", "H", hourly.dow.astype(str))

    # 1. Регрессия на дневных суммах по маршрутам с историей
    daily = hourly.groupby("date", as_index=False).agg(y=("y", "sum"), day_type=("day_type", "first"), precip=("precip", "first"), snow=("snow", "first"), tmean=("tmean", "first"))
    X, names = design(daily)
    beta, se = ols(X, np.log(daily.y.to_numpy()))
    effects = {}
    print(f"\nДней в регрессии: {len(daily)}; источники: календарь isdayoff.ru, погода Open-Meteo")
    print(f"{'фактор':<14}{'эффект':>9}{'95% ДИ':>20}{'t':>7}{'дней':>7}")
    for key, label in [("holiday", "Праздник в будни"), ("work_weekend", "Рабочая суббота/воскр."), ("short", "Предпраздничный сокращённый"), ("rain", "Сильные осадки ≥5 мм"), ("snow", "Снегопад ≥2 см"), ("cold", "Мороз ≤ −10 °C"), ("hot", "Жара ≥ 25 °C")]:
        if key not in names:
            effects[key] = {"label": label, "effect": None, "ci95": None, "t": None, "days": 0, "significant": False}
            print(f"{label:<28}  в данных не встречается")
            continue
        i = names.index(key)
        n = int(X[:, i].sum())
        eff = float(np.exp(beta[i]) - 1)
        lo, hi = float(np.exp(beta[i] - 1.96 * se[i]) - 1), float(np.exp(beta[i] + 1.96 * se[i]) - 1)
        t = float(beta[i] / se[i])
        effects[key] = {"label": label, "effect": round(eff, 4), "ci95": [round(lo, 4), round(hi, 4)], "t": round(t, 2), "days": n, "significant": bool(abs(t) >= 2 and n >= 3)}
        print(f"{label:<28}{eff * 100:>+7.1f}%   [{lo * 100:+6.1f}%; {hi * 100:+6.1f}%]{t:>7.1f}{n:>6}")

    # 2. Отложенные периоды. Эффект праздника и погоды оценивается только по обучающей части окна.
    windows = [("Сен–окт (обучение янв–авг)", "2025-09-01", "2025-10-31"), ("Май–июнь (обучение янв–апр)", "2025-05-01", "2025-06-30"), ("Окт (обучение янв–сен)", "2025-10-01", "2025-10-31")]
    backtests, weather_rows = [], []
    print(f"\n{'окно':<28}{'вариант':<38}{'score c=1.086':>14}{'лучший c':>10}{'праздн. дни':>13}")
    for title, a, b in windows:
        train, test = hourly[hourly.date < a], hourly[(hourly.date >= a) & (hourly.date <= b)]
        dtr = daily[daily.date < a]
        Xt, nm = design(dtr)
        bt, _ = ols(Xt, np.log(dtr.y.to_numpy()))
        bmap = dict(zip(nm, bt))
        hol_factor = float(np.exp(bmap.get("holiday", 0.0)))
        y = test.y.to_numpy()
        hol = (test.day_type == "holiday").to_numpy()
        p_week = predict(train, test, "weekday_key")
        p_hol = np.where(hol, p_week * hol_factor, p_week)                      # + поправка на праздничные будни
        p_cls = predict(train, test, "dow_hol_key")                             # отдельный профиль праздничных дней
        wx = np.zeros(len(test))
        for f, col, cond in [("rain", "precip", lambda v: v >= 5), ("snow", "snow", lambda v: v >= 2), ("cold", "tmean", lambda v: v <= -10), ("hot", "tmean", lambda v: v >= 25)]:
            wx += bmap.get(f, 0.0) * cond(test[col]).to_numpy()
        variants = {"A. по дню недели (текущая модель)": p_week, "B. A + поправка на праздничные будни": p_hol, "C. отдельный профиль праздничных дней": p_cls, "D. B + фактическая погода": p_hol * np.exp(wx)}
        rows = {}
        for name, p in variants.items():
            c = best_scale(y, p)
            rows[name] = {"score": round(score(y, p * CALIBRATION), 4), "score_best_scale": round(score(y, p * c), 4), "best_scale": round(float(c), 3),
                          "score_holidays": round(score(y[hol], p[hol] * CALIBRATION), 4) if hol.any() else None}
            sh = rows[name]["score_holidays"]
            print(f"{title:<28}{name:<38}{rows[name]['score']:>14.4f}{rows[name]['score_best_scale']:>10.4f}{('—' if sh is None else f'{sh:.4f}'):>13}")
        backtests.append({"window": title, "holiday_days": int(test[test.day_type == "holiday"].date.nunique()), "holiday_factor_from_train": round(hol_factor, 4), "models": rows})

    # 4. Календарь прогнозного периода
    nd = cal[(cal.date >= "2025-11-01") & (cal.date <= "2025-12-31")]
    special = nd[nd.day_type.isin(["holiday", "weekend", "short", "work_weekend"]) & ~((nd.day_type == "weekend"))]
    print("\nОсобые дни ноября–декабря 2025:", ", ".join(f"{d:%d.%m}({t})" for d, t in zip(special.date, special.day_type)))
    sub = pd.read_csv(ROOT / "submission.csv", sep=";", parse_dates=["date"])
    hol_dates = set(nd[nd.day_type == "holiday"].date)
    on_hol = sub[sub.date.isin(hol_dates)].prediction.sum()
    eff = effects["holiday"]["effect"]
    gain = -eff * on_hol / sub.prediction.sum()
    print(f"\nПрогноз модели на праздничные будни ({len(hol_dates)} дн.): {on_hol:,.0f} посадок, {on_hol / sub.prediction.sum() * 100:.1f}% всего. "
          f"Если эффект {eff * 100:+.1f}% верен, завышение ≈ {gain * 100:.1f} п.п. WAPE (оценка сверху для этих дней)")
    proposal = sub.copy()
    mask = proposal.date.isin(hol_dates)
    proposal.loc[mask, "prediction"] = np.rint(proposal.loc[mask, "prediction"] * (1 + eff)).astype(int)
    proposal["date"] = proposal.date.dt.strftime("%Y-%m-%d")
    proposal.to_csv(ROOT / "artifacts" / "submission_calendar_proposal.csv", sep=";", index=False)
    print(f"Предложение для ML (submission.csv НЕ изменён): artifacts/submission_calendar_proposal.csv, изменены только строки праздничных будних дней ({int(mask.sum())} строк)")
    out = {"sources": {"calendar": "https://isdayoff.ru/", "weather": "https://open-meteo.com/en/docs/historical-weather-api"}, "effects": effects, "backtests": backtests, "days_used": int(len(daily)), "expected_gain_pp": round(gain * 100, 2), "forecast_holiday_share": round(on_hol / sub.prediction.sum(), 4),
           "forecast_calendar": [{"date": f"{d:%Y-%m-%d}", "type": t} for d, t in zip(nd.date, nd.day_type)]}
    (EXT / "effects.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nЗаписано: {EXT / 'effects.json'}")


if __name__ == "__main__":
    configure_console()
    main()
