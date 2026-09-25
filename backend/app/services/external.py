from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from .. import config

SOURCES = {
    "calendar": "https://isdayoff.ru/",
    "weather": "https://open-meteo.com/en/docs/historical-weather-api",
}
_TYPE_NAMES = {"holiday": "праздничный или перенесённый выходной в будни", "weekend": "выходной", "short": "сокращённый рабочий день", "work_weekend": "рабочий выходной", "work": "рабочий день"}


@dataclass
class External:
    calendar: dict[date, str] = field(default_factory=dict)
    effects: dict = field(default_factory=dict)
    weather: dict[date, dict] = field(default_factory=dict)

    @property
    def holiday_effect(self) -> float | None:
        e = self.effects.get("holiday")
        return e["effect"] if e and e.get("effect") is not None else None

    @property
    def holiday_factor(self) -> float:
        return 1 + (self.holiday_effect or 0.0)

    def weather_factor(self, w: dict) -> float:
        """Множитель дня по измеренным эффектам осадков (≥ 5 мм) и снегопада (≥ 2 см); учитываются только подтверждённые."""
        factor = 1.0
        for key, hit in (("rain", w["precip"] >= 5), ("snow", w["snow"] >= 2)):
            e = self.effects.get(key)
            if hit and e and e.get("significant") and e.get("effect") is not None:
                factor *= 1 + e["effect"]
        return factor

    @property
    def holidays(self) -> list[date]:
        """Праздничные будни внутри периода прогноза."""
        return [d for d, t in sorted(self.calendar.items()) if t == "holiday" and config.FORECAST_START <= d <= config.FORECAST_END]


def load() -> External:
    ext = External()
    cal, eff = config.EXTERNAL_DIR / "calendar_2025.csv", config.EXTERNAL_DIR / "effects.json"
    if cal.exists():
        df = pd.read_csv(cal)
        ext.calendar = {date.fromisoformat(d): t for d, t in zip(df["date"], df["day_type"])}
    if eff.exists():
        ext.effects = json.loads(eff.read_text(encoding="utf-8"))["effects"]
    wf = config.EXTERNAL_DIR / "weather_2025.csv"
    if wf.exists():
        w = pd.read_csv(wf)
        ext.weather = {date.fromisoformat(d): {"tmean": float(t), "precip": float(p), "snow": float(sn)} for d, t, p, sn in zip(w["date"], w["tmean"], w["precip"], w["snow"])}
    return ext


def weather_days(ext: External, start: date, end: date) -> list[dict]:
    out = []
    for d, w in sorted(ext.weather.items()):
        if start <= d <= end:
            flags = (["осадки ≥ 5 мм"] if w["precip"] >= 5 else []) + (["снегопад ≥ 2 см"] if w["snow"] >= 2 else [])
            out.append({"date": d.isoformat(), "tmean": w["tmean"], "precip_mm": w["precip"], "snow_cm": w["snow"], "flags": flags, "factor": round(ext.weather_factor(w), 4)})
    return out


def calendar_days(ext: External, start: date, end: date) -> list[dict]:
    factor = ext.holiday_factor
    return [
        {"date": d.isoformat(), "weekday": d.weekday(), "type": t, "description": _TYPE_NAMES[t], "factor": round(factor, 4) if t == "holiday" else 1.0}
        for d, t in sorted(ext.calendar.items())
        if start <= d <= end
    ]


def presets(ext: External) -> dict:
    """Ориентиры для коэффициентов: измеренные на данных 2025 (с доверительным интервалом) и экспертные (помечены)."""
    def measured(key: str, label: str) -> list[dict]:
        e = ext.effects.get(key)
        if not e or not e.get("significant"):
            return []
        lo, hi = e["ci95"]
        return [{"label": label, "value": round(1 + e["effect"], 3), "measured": True, "ci95": [round(1 + lo, 3), round(1 + hi, 3)], "days": e["days"]}]

    return {
        "disclaimer": (
            "Значения с пометкой measured измерены на посадках января–октября 2025 (регрессия по дневным суммам, 95% ДИ). "
            "Остальные — экспертные ориентиры, на данных не проверялись. Эффект погоды статистически значим, но на отложенных "
            "периодах учёт фактической погоды точность прогноза не повышает, поэтому он предназначен для сценарного анализа."
        ),
        "limits": {"factor": [0.5, 1.5], "rule": [0.1, 3.0]},
        "sources": SOURCES,
        "weather": [{"label": "Обычная погода", "value": 1.0, "measured": False}]
        + measured("rain", "Сильные осадки (≥ 5 мм за сутки)")
        + measured("snow", "Снегопад (≥ 2 см за сутки)"),
        "event": [
            {"label": "Без событий", "value": 1.0, "measured": False},
            {"label": "Крупное мероприятие вдоль маршрута", "value": 1.15, "measured": False},
            {"label": "Ремонт или перекрытие путей", "value": 0.8, "measured": False},
        ],
        "season": [],  # праздники и переносы учитываются опцией calendar в /forecast/adjusted
        "calendar": {
            "holiday_factor": round(ext.holiday_factor, 4),
            "holiday_effect_ci95": ext.effects.get("holiday", {}).get("ci95"),
            "days": [d.isoformat() for d in ext.holidays],
        },
    }
