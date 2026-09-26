from __future__ import annotations

import asyncio
import json
import os
import time

from starlette.concurrency import run_in_threadpool

from .. import config
from ..store import DataStore


def _version(stamp: object) -> str:
    """Отпечаток данных: (mtime, размер) файла принятых данных без БД или номер ревизии в PostgreSQL."""
    if stamp is None:
        return "0"
    if isinstance(stamp, tuple):
        return f"{stamp[0]:x}-{stamp[1]}"
    return f"r{stamp}"


def snapshot(store: DataStore) -> dict:
    """Текущее состояние данных: version меняется, когда любой воркер принял новые валидации."""
    return {
        "version": _version(store._stamp),
        "history_end": store.history_end.isoformat(),
        "ingested_boardings": store.ingested_boardings,
        "updated_at": store.updated_at.isoformat(timespec="seconds"),
        "worker_pid": os.getpid(),
        "ml_model": store.ml_status,
    }


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream(request, store: DataStore, wait: float):
    """SSE: событие update сразу при подключении и при каждом изменении данных, комментарий-пульс между ними."""
    yield "retry: 3000\n\n"
    started = last_beat = time.monotonic()
    last_version = None
    while not await request.is_disconnected():
        await run_in_threadpool(store.refresh)  # дёшево: сравнивает отпечаток файла, пересборка только при изменении
        snap = snapshot(store)
        if snap["version"] != last_version:
            last_version = snap["version"]
            last_beat = time.monotonic()
            yield _event("update", snap)
        elif time.monotonic() - last_beat >= config.LIVE_HEARTBEAT_SECONDS:
            last_beat = time.monotonic()
            yield ": ping\n\n"
        if wait and time.monotonic() - started >= wait:
            break
        await asyncio.sleep(config.LIVE_POLL_SECONDS)
