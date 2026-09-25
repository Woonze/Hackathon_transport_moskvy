from __future__ import annotations

import fcntl
import logging
from contextlib import contextmanager

import pandas as pd

from .. import config

log = logging.getLogger("tram")
COLUMNS = ["batch_id", "route", "date", "hour", "boardings"]


def stamp() -> tuple[int, int] | None:
    """Отпечаток файла: воркеры сравнивают его, чтобы заметить чужую запись."""
    try:
        st = config.OVERLAY.stat()
    except FileNotFoundError:
        return None
    return st.st_mtime_ns, st.st_size


def empty() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS).astype({"route": "int64", "date": "datetime64[ns]", "hour": "int64", "boardings": "int64"})


def read() -> pd.DataFrame:
    """Читает принятые данные, пропуская повреждённые строки (обрыв записи, мусор): сервис не должен падать из-за файла."""
    if stamp() is None or config.OVERLAY.stat().st_size == 0:
        return empty()
    df = pd.read_csv(config.OVERLAY, sep=";", dtype=str, on_bad_lines="skip")
    if list(df.columns) != COLUMNS:
        log.error("Файл принятых данных %s: неожиданные столбцы %s, файл проигнорирован", config.OVERLAY, list(df.columns))
        return empty()
    for col in ("route", "hour", "boardings"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce", format="%Y-%m-%d")
    good = df.dropna(subset=["route", "date", "hour", "boardings"])
    good = good[good["hour"].between(0, 23) & (good["boardings"] >= 0)]
    if len(good) != len(df):
        log.warning("Файл принятых данных: пропущено повреждённых строк: %d из %d", len(df) - len(good), len(df))
    return good.astype({"route": "int64", "hour": "int64", "boardings": "int64"}).reset_index(drop=True)


@contextmanager
def _locked():
    config.OVERLAY.parent.mkdir(parents=True, exist_ok=True)
    with open(config.OVERLAY.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def append(batch_id: str, agg: pd.DataFrame) -> bool:
    """Дописывает пакет; False, если пакет с таким batch_id уже принят (идемпотентность)."""
    with _locked():
        exists = config.OVERLAY.exists()
        if exists and batch_id in set(read()["batch_id"]):
            return False
        if exists and config.OVERLAY.stat().st_size:
            with open(config.OVERLAY, "rb+") as fh:  # прежняя запись могла оборваться без перевода строки
                fh.seek(-1, 2)
                if fh.read(1) != b"\n":
                    fh.write(b"\n")
        out = agg.assign(batch_id=batch_id)[COLUMNS]
        out.to_csv(config.OVERLAY, sep=";", index=False, mode="a", header=not exists, date_format="%Y-%m-%d")
        return True
