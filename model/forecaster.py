"""Обучаемая модель пассажиропотока и общий офлайн/потоковый inference-контур."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from time import perf_counter

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

MODEL_NAME = "HistGradientBoostingRegressor"
MODEL_VERSION = "3"
GROUP_KEYS = ["route", "weekday", "hour"]
DAY_TYPES = ["work", "weekend", "holiday", "short", "work_weekend"]


@dataclass(frozen=True)
class FitResult:
    predictions: pd.DataFrame
    trained_at: str
    training_rows: int
    duration_ms: float
    model_name: str = MODEL_NAME
    model_version: str = MODEL_VERSION


def dense_history(history: pd.DataFrame, routes: list[int], observed_dates: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """Заполняет нулями часы только тех дат, которые подтверждены как полные."""
    data = history[["route", "date", "hour", "boardings"]].copy()
    data["date"] = pd.to_datetime(data["date"])
    days = pd.DatetimeIndex(observed_dates).unique().sort_values() if observed_dates is not None else pd.date_range(data.date.min(), data.date.max(), freq="D")
    index = pd.MultiIndex.from_product([routes, days, range(24)], names=["route", "date", "hour"])
    observed = data.groupby(["route", "date", "hour"], as_index=True).boardings.sum()
    out = observed.reindex(index, fill_value=0).rename("boardings").reset_index()
    out["boardings"] = out["boardings"].astype(float)
    out["weekday"] = out.date.dt.dayofweek.astype(int)
    return out


def _day_type(dates: pd.Series, calendar: dict[date, str]) -> pd.Series:
    dow = dates.dt.dayofweek
    values = dates.dt.date.map(calendar)
    fallback = np.where(dow >= 5, "weekend", "work")
    return pd.Series(values, index=dates.index).fillna(pd.Series(fallback, index=dates.index))


def _profile_features(
    train: pd.DataFrame,
    target: pd.DataFrame,
    routes: list[int],
    calendar: dict[date, str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Historical route×weekday×hour level; train rows use leave-one-row-out values."""
    stats = train.groupby(GROUP_KEYS, observed=True).boardings.agg(["sum", "count"])
    train_index = pd.MultiIndex.from_frame(train[GROUP_KEYS])
    total = stats["sum"].reindex(train_index).to_numpy(dtype=float)
    count = stats["count"].reindex(train_index).to_numpy(dtype=float)
    train_base = np.divide(
        total - train.boardings.to_numpy(dtype=float),
        np.maximum(count - 1.0, 1.0),
    )

    target_index = pd.MultiIndex.from_frame(target[GROUP_KEYS])
    profile = (stats["sum"] / stats["count"]).reindex(target_index).fillna(0).to_numpy(dtype=float)

    def build(rows: pd.DataFrame, base: np.ndarray) -> pd.DataFrame:
        dates = pd.to_datetime(rows.date)
        days = (dates - pd.Timestamp("2025-01-01")).dt.days.to_numpy(dtype=float)
        frame = pd.DataFrame(
            {
                "route": pd.Categorical(rows.route.astype(int), categories=routes),
                "weekday": pd.Categorical(rows.weekday.astype(int), categories=range(7)),
                "hour": pd.Categorical(rows.hour.astype(int), categories=range(24)),
                "month": pd.Categorical(dates.dt.month.astype(int), categories=range(1, 13)),
                "day_type": pd.Categorical(_day_type(dates, calendar), categories=DAY_TYPES),
                "profile_mean": base,
                "profile_log": np.log1p(base),
                "day_index": days / 365.25,
                "year_sin": np.sin(2 * np.pi * days / 365.25),
                "year_cos": np.cos(2 * np.pi * days / 365.25),
            }
        )
        return frame

    return build(train, train_base), build(target, profile)


def fit_predict(
    history: pd.DataFrame,
    target: pd.DataFrame,
    routes: list[int],
    calendar: dict[date, str] | None = None,
    observed_dates: pd.DatetimeIndex | None = None,
) -> FitResult:
    """Обучает ML-модель заново на актуальной истории и выдаёт прогноз целевых часов."""
    started = perf_counter()
    calendar = calendar or {}
    train = dense_history(history, routes, observed_dates)
    out = target[["route", "date", "hour"]].copy()
    out["date"] = pd.to_datetime(out.date)
    out["weekday"] = out.date.dt.dayofweek.astype(int)
    if train.empty or out.empty:
        out["prediction"] = 0
        return FitResult(out[["route", "date", "hour", "prediction"]], datetime.now(timezone.utc).isoformat(), len(train), 0.0)

    x_train, x_target = _profile_features(train, out, routes, calendar)
    model = HistGradientBoostingRegressor(
        loss="absolute_error",
        learning_rate=0.05,
        max_iter=300,
        max_leaf_nodes=63,
        min_samples_leaf=50,
        l2_regularization=10.0,
        categorical_features="from_dtype",
        early_stopping=False,
        random_state=42,
    )
    model.fit(x_train, train.boardings.to_numpy(dtype=float))
    values = np.maximum(model.predict(x_target), 0.0)

    observed_routes = set(history.loc[history.boardings > 0, "route"].astype(int))
    values[out.route.isin(set(routes) - observed_routes).to_numpy()] = 0.0
    out["prediction"] = np.rint(values).astype(int)
    duration = (perf_counter() - started) * 1000
    return FitResult(
        predictions=out[["route", "date", "hour", "prediction"]],
        trained_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        training_rows=len(train),
        duration_ms=round(duration, 1),
    )
