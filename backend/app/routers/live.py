from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ..schemas import ErrorBody
from ..services import live

router = APIRouter(tags=["live"])


@router.get(
    "/stream",
    summary="Поток обновлений данных (Server-Sent Events)",
    description=(
        "Открытое соединение text/event-stream. Событие `update` приходит сразу при подключении и затем каждый раз, "
        "когда приняты новые валидации (в том числе другим воркером): в нём version, history_end, ingested_boardings, updated_at. "
        "Между событиями раз в 15 с идёт комментарий-пульс. Браузерный EventSource переподключается сам. "
        "Параметр wait ограничивает время соединения (секунды), 0 — без ограничения."
    ),
    responses={200: {"content": {"text/event-stream": {}}}, 422: {"model": ErrorBody}},
)
def stream(request: Request, wait: float = Query(0, ge=0, le=86400, description="Сколько секунд держать соединение; 0 — пока клиент не отключится")):
    return StreamingResponse(
        live.stream(request, request.app.state.store, wait),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
