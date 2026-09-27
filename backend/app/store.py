from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import config
from .services import external, overlay, regime, stopmodel

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
    def __init__(self) -> None:
        self.cache: dict = {}
        self._lock = threading.Lock()
        self._stamp: object = object()
        pred = pd.read_csv(config.SUBMISSION, sep=";", parse_dates=["date"])
        self._labels = pd.concat([pd.read_csv(p, sep=";") for p in config.LABELS], ignore_index=True)
        self._labels["date"] = pd.to_datetime(self._labels["date"])
        self.routes = sorted(pred["route"].unique().astype(int).tolist())
        self.forecast = Series.from_frame(pred, "prediction", self.routes, config.FORECAST_START, config.FORECAST_END)
        self.forecast_rows = int(self.forecast.values.size)
        self.stops = stopmodel.build_index(self.routes)
        self.external = external.load()
        self.refresh(force=True)

    def refresh(self, force: bool = False) -> bool:
        """Пересобирает историю, если файл принятых данных изменился (в т.ч. другим воркером)."""
        stamp = overlay.stamp()
        if not force and stamp == self._stamp:
            return False
        with self._lock:
            if not force and stamp == self._stamp:
                return False
            try:
                self._apply(overlay.read())
            except Exception:  # повреждённый файл не должен ронять ни запросы, ни запуск сервиса
                log.exception("Не удалось применить принятые данные, оставляем прежнее состояние")
                if not hasattr(self, "history"):
                    self._apply(overlay.empty())
            self._stamp = stamp
        self.cache.clear()
        return True

    def _apply(self, extra: pd.DataFrame) -> None:
        extra = extra[extra["route"].isin(self.routes)]  # чужой/неизвестный маршрут не должен портить кубы истории
        frame = pd.concat([self._labels, extra.drop(columns="batch_id")], ignore_index=True)
        last = max(config.HISTORY_END, extra["date"].max().date()) if len(extra) else config.HISTORY_END
        history = Series.from_frame(frame, "boardings", self.routes, config.HISTORY_START, last)
        self._rebuild(history, last)
        # self.* ниже — только после успешного _rebuild, чтобы ошибка не оставляла store в частично обновлённом состоянии
        self.ingested_boardings = int(extra["boardings"].sum()) if len(extra) else 0
        self.updated_at = datetime.now(timezone.utc)

    def _rebuild(self, history: Series, last) -> None:
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
