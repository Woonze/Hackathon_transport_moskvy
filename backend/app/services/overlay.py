from __future__ import annotations

import errno
import logging
import os
import time
from contextlib import contextmanager

if os.name == "nt":
    import msvcrt
else:
    import fcntl

import pandas as pd

from .. import config
from ..errors import ApiError

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


def _has_valid_header() -> bool:
    """Проверяет, что файл можно безопасно продолжить дополнять строками."""
    if stamp() is None or config.OVERLAY.stat().st_size == 0:
        return False
    try:
        return list(pd.read_csv(config.OVERLAY, sep=";", dtype=str, nrows=0).columns) == COLUMNS
    except (OSError, UnicodeError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return False


def _write_header() -> None:
    """Атомарно создаёт чистый CSV, если предыдущий файл пуст или повреждён."""
    temporary = config.OVERLAY.with_name(f"{config.OVERLAY.name}.{os.getpid()}.tmp")
    try:
        with open(temporary, "w", encoding="utf-8", newline="") as fh:
            pd.DataFrame(columns=COLUMNS).to_csv(fh, sep=";", index=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, config.OVERLAY)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            log.warning("Не удалось удалить временный файл %s", temporary, exc_info=True)


@contextmanager
def _locked():
    config.OVERLAY.parent.mkdir(parents=True, exist_ok=True)
    # Keep one stable byte in the lock file: msvcrt.locking cannot lock an
    # empty file, while flock locks the file itself and works on Unix.
    with open(config.OVERLAY.with_suffix(".lock"), "a+b") as lock:
        if os.name == "nt":
            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            while True:
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EDEADLK, errno.EAGAIN):
                        raise
                    time.sleep(0.05)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def append(batch_id: str, agg: pd.DataFrame) -> bool:
    """Дописывает пакет; False, если пакет с таким batch_id уже принят (идемпотентность)."""
    with _locked():
        valid_file = _has_valid_header()
        if valid_file:
            saved = read()
            previous = saved.loc[saved["batch_id"] == batch_id, ["route", "date", "hour", "boardings"]]
            if len(previous):
                columns = ["route", "date", "hour", "boardings"]
                def canonical(frame: pd.DataFrame) -> list[tuple[int, str, int, int]]:
                    return sorted(
                        (int(route), pd.Timestamp(day).date().isoformat(), int(hour), int(count))
                        for route, day, hour, count in frame[columns].itertuples(index=False, name=None)
                    )

                if canonical(previous) == canonical(agg[columns]):
                    return False
                raise ApiError(409, "Идентификатор пакета уже использован для других данных", "batch_id_conflict")
        else:
            if config.OVERLAY.exists():
                log.warning("Файл принятых данных %s пуст или имеет неверный заголовок; создаём заново", config.OVERLAY)
            _write_header()
        if valid_file and config.OVERLAY.stat().st_size:
            with open(config.OVERLAY, "rb+") as fh:  # прежняя запись могла оборваться без перевода строки
                fh.seek(-1, 2)
                if fh.read(1) != b"\n":
                    fh.write(b"\n")
        out = agg.assign(batch_id=batch_id)[COLUMNS]
        out.to_csv(config.OVERLAY, sep=";", index=False, mode="a", header=False, date_format="%Y-%m-%d")
        return True
