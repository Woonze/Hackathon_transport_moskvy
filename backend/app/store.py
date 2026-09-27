from __future__ import annotations

import logging
import threading
import hashlib
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from . import config
from .services import external, overlay, regime, stopmodel
from model.forecaster import MODEL_NAME, MODEL_VERSION, fit_predict

log = logging.getLogger("tram")


class Series:
    """Плотный куб посадок [маршрут, день, час] и календарь к нему."""

    def __init__(self, routes: list[int], dates: pd.DatetimeIndex, values: np.ndarray):
        self.routes, self.dates, self.values = routes, dates, values
        self.route_index = {r: i for i, r in enumerate(routes)}
        self.date_str = dates.strftime("%Y-%m-%d").tolist()
        self.month_str = dates.strftime("%Y-%m").tolist()
        self.weekday = dates.dayofweek.to_numpy()

    @classmethod
    def from_frame(cls, frame: pd.DataFrame, value: str, routes: list[int], first, last) -> Series:
        dates = pd.date_range(first, last, freq="D")
        cube = np.zeros((len(routes), len(dates), 24), dtype=np.int64)
        ri = frame["route"].map({r: i for i, r in enumerate(routes)}).to_numpy()
        di = (frame["date"] - dates[0]).dt.days.to_numpy()
        ok = (di >= 0) & (di < len(dates))
        np.add.at(cube, (ri[ok], di[ok], frame["hour"].to_numpy()[ok]), np.rint(frame[value].to_numpy()[ok]).astype(np.int64))
        return cls(routes, dates, cube)

    def span(self, start, end) -> tuple[int, int]:
        """Полуинтервал индексов дней, пересекающий [start, end]."""
        lo = int(self.dates.searchsorted(pd.Timestamp(start), side="left"))
        hi = int(self.dates.searchsorted(pd.Timestamp(end), side="right"))
        return lo, hi


class DataStore:
    def __init__(self, database=None) -> None:
        self.database = database
        self.cache: dict = {}
        self._lock = threading.Lock()
        self._stamp: object = object()
        pred = pd.read_csv(config.SUBMISSION, sep=";", parse_dates=["date"])
        self._labels = pd.concat([pd.read_csv(p, sep=";") for p in config.LABELS], ignore_index=True)
        self._labels["date"] = pd.to_datetime(self._labels["date"])
        self.routes = sorted(pred["route"].unique().astype(int).tolist())
        self.forecast = Series.from_frame(pred, "prediction", self.routes, config.FORECAST_START, config.FORECAST_END)
        self.forecast_rows = int(self.forecast.values.size)
        self._training_signature: str | None = None
        self.ml_status = {
            "name": MODEL_NAME,
            "version": MODEL_VERSION,
            "training_rows": 0,
            "duration_ms": 0.0,
            "updated_at": None,
            "updates": 0,
            "calendar_in_model": False,
            "pending_boardings": 0,
        }
        self.stops = stopmodel.build_index(self.routes)
        self.external = external.load()
        self.refresh(force=True)

    def refresh(self, force: bool = False) -> bool:
        """Пересобирает историю, если файл принятых данных изменился (в т.ч. другим воркером)."""
        stamp = self.database.ingest_revision() if self.database else overlay.stamp()
        if not force and stamp == self._stamp:
            return False
        with self._lock:
            if not force and stamp == self._stamp:
                return False
            try:
                self._apply(self.database.read_ingested() if self.database else overlay.read())
            except Exception:  # повреждённый файл не должен ронять ни запросы, ни запуск сервиса
                log.exception("Не удалось применить принятые данные, оставляем прежнее состояние")
                if not hasattr(self, "history"):
                    self._apply(overlay.empty())
            self._stamp = stamp
        self.cache.clear()
        return True

    def _apply(self, extra: pd.DataFrame) -> None:
        extra = extra[extra["route"].isin(self.routes)]  # чужой/неизвестный маршрут не должен портить кубы истории
        frame = pd.concat([self._labels, extra.drop(columns=["batch_id", "complete"])], ignore_index=True)
        last = max(config.HISTORY_END, extra["date"].max().date()) if len(extra) else config.HISTORY_END
        history = Series.from_frame(frame, "boardings", self.routes, config.HISTORY_START, last)
        completed = pd.DatetimeIndex(extra.loc[extra.complete & extra.date.gt(pd.Timestamp(config.HISTORY_END)), "date"].unique()).sort_values()
        usable = extra.date.le(pd.Timestamp(config.HISTORY_END)) | extra.date.isin(completed)
        training_frame = pd.concat([self._labels, extra.loc[usable, ["route", "date", "hour", "boardings"]]], ignore_index=True)
        training_frame["date"] = pd.to_datetime(training_frame["date"]).astype("datetime64[ns]")
        training_dates = pd.date_range(config.HISTORY_START, config.HISTORY_END, freq="D").union(completed)
        last_complete = max(config.HISTORY_END, completed.max().date()) if len(completed) else config.HISTORY_END
        self._rebuild(history, last, training_frame, training_dates, last_complete)
        # Обновляем публичное состояние только после успешной пересборки, чтобы ошибка не оставляла частично применённый пакет.
        self.ingested_boardings = int(extra["boardings"].sum()) if len(extra) else 0
        self.updated_at = datetime.now(timezone.utc)
        self.ml_status["pending_boardings"] = int(extra.loc[~usable, "boardings"].sum())

    def _rebuild(self, history: Series, last, training_frame: pd.DataFrame, training_dates: pd.DatetimeIndex, last_complete) -> None:
        self._fit_streaming_forecast(training_frame, training_dates, last_complete)
        lo, hi = history.span(config.RECENT_START, config.HISTORY_END)
        daily = history.values[:, lo:hi].sum(axis=2)
        wd = history.weekday[lo:hi]
        self.weekday_average = [
            {"route": r, "weekday": d, "passengers": float(daily[i, wd == d].mean())}
            for i, r in enumerate(self.routes)
            for d in range(7)
            if (wd == d).any()
        ]
        self.route_summary = [
            {
                "id": r,
                "name": f"Маршрут {r}",
                "historical_total": int(history.values[i].sum()),
                "forecast_total": int(self.forecast.values[i].sum()),
            }
            for i, r in enumerate(self.routes)
        ]
        self.history_end = last
        self.history = history
        self.regime = regime.compute(history, self.external.calendar)

    def _fit_streaming_forecast(self, training_frame: pd.DataFrame, training_dates: pd.DatetimeIndex, last_complete) -> None:
        """Retrain after complete-day data changes; partial stream records remain pending."""
        fingerprint = pd.util.hash_pandas_object(training_frame[["route", "date", "hour", "boardings"]], index=False).to_numpy().tobytes()
        signature = hashlib.blake2b(fingerprint, digest_size=16).hexdigest()
        if signature == self._training_signature:
            return
        first = max(config.FORECAST_START, last_complete + timedelta(days=1))
        if first > config.FORECAST_END:
            return
        dates = pd.date_range(first, config.FORECAST_END, freq="D")
        target = pd.MultiIndex.from_product(
            [self.routes, dates, range(24)], names=["route", "date", "hour"]
        ).to_frame(index=False)
        try:
            fitted = fit_predict(training_frame, target, self.routes, self.external.calendar, observed_dates=training_dates)
            values = self.forecast.values.copy()
            route_idx = fitted.predictions.route.map(self.forecast.route_index).to_numpy(dtype=int)
            day_idx = (fitted.predictions.date - self.forecast.dates[0]).dt.days.to_numpy(dtype=int)
            hour_idx = fitted.predictions.hour.to_numpy(dtype=int)
            values[route_idx, day_idx, hour_idx] = fitted.predictions.prediction.to_numpy(dtype=np.int64)
            self.forecast = Series(self.routes, self.forecast.dates, values)
            self.ml_status = {
                "name": fitted.model_name,
                "version": fitted.model_version,
                "training_rows": fitted.training_rows,
                "duration_ms": fitted.duration_ms,
                "updated_at": fitted.trained_at,
                "updates": self.ml_status["updates"] + 1,
                "calendar_in_model": bool(self.external.calendar),
                "pending_boardings": self.ml_status.get("pending_boardings", 0),
            }
            self._training_signature = signature
        except Exception:
            # Keep the latest valid prediction live if a newly ingested batch is malformed.
            log.exception("Не удалось переобучить потоковую ML-модель; сохранён прежний прогноз")
