from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import ORJSONResponse

from .. import config
from ..errors import ApiError
from ..schemas import ErrorBody, IngestRequest
from ..services import ingest


def require_key(x_api_key: str | None = Header(None, description="Ключ приёма данных (если на сервере задан INGEST_API_KEY)")) -> None:
    expected = config.INGEST_API_KEY
    if expected and not (x_api_key and hmac.compare_digest(x_api_key.encode(), expected.encode())):
        raise ApiError(401, "Приём данных защищён: передайте корректный заголовок X-API-Key", "unauthorized")


router = APIRouter()


@router.post(
    "/ingest/validations",
    summary="Приём пакета сырых валидаций",
    description=(
        "Нормализует записи (успешные валидации, маршрут из ngpt_route, час из tran_date_time), "
        "отбрасывает дубли по паре device_no + tran_no внутри пакета и добавляет посадки в историю. "
        "Повторная отправка пакета с тем же batch_id (или тем же содержимым) не задваивает данные."
    ),
    responses={401: {"model": ErrorBody}, 422: {"model": ErrorBody}},
    dependencies=[Depends(require_key)],
)
def ingest_validations(body: IngestRequest, request: Request):
    return ORJSONResponse(ingest.process(body.records, body.batch_id, request.app.state.store, complete=body.complete))
