from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse

log = logging.getLogger("tram")


class ApiError(Exception):
    """Ошибка с понятным пользователю текстом; `code` — машиночитаемый признак."""

    def __init__(self, status: int, detail: str, code: str = "bad_request"):
        self.status, self.detail, self.code = status, detail, code


def _body(status: int, detail: str, code: str) -> ORJSONResponse:
    return ORJSONResponse({"detail": detail, "code": code}, status_code=status)


def _explain(err: dict) -> str:
    name = ".".join(str(p) for p in err["loc"] if p not in ("query", "body", "path"))
    kind = err["type"]
    if kind == "enum":
        text = f"допустимые значения: {err.get('ctx', {}).get('expected', '')}".rstrip(": ")
    elif kind.startswith("date"):
        text = "ожидается дата в формате ГГГГ-ММ-ДД"
    elif kind.startswith("int"):
        text = "ожидается целое число"
    elif kind.startswith("float") or kind == "decimal_parsing":
        text = "ожидается число"
    elif kind in ("greater_than_equal", "less_than_equal", "greater_than", "less_than"):
        ctx = err.get("ctx", {})
        text = "значение " + (f"не меньше {ctx['ge']}" if "ge" in ctx else f"не больше {ctx['le']}" if "le" in ctx else f"вне допустимых границ ({err['msg']})")
    elif kind == "too_short":
        n = err.get("ctx", {}).get("min_length", 1)
        text = "список не должен быть пустым" if n == 1 else f"в списке должно быть не меньше {n} элементов"
    elif kind == "too_long":
        text = f"допустимо не больше {err.get('ctx', {}).get('max_length', '')} элементов"
    elif kind == "string_pattern_mismatch":
        text = "допустимы только буквы латиницы, цифры, точка, дефис и подчёркивание"
    elif kind in ("string_too_short", "string_too_long"):
        text = "недопустимая длина строки"
    elif kind.endswith("_type"):
        text = "значение неверного типа"
    elif kind == "value_error":
        text = err["msg"].removeprefix("Value error, ")
    elif kind == "missing":
        text = "обязательный параметр не указан"
    else:
        text = err["msg"]
    return f"Некорректный параметр «{name}»: {text}"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError):
        return _body(exc.status, exc.detail, exc.code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        return _body(422, "; ".join(_explain(e) for e in exc.errors()), "validation_error")

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "Ошибка запроса"
        if exc.status_code == 404:
            detail = "Ресурс не найден" if detail == "Not Found" else detail
        return _body(exc.status_code, detail, "http_error")

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception):
        log.exception("Необработанная ошибка", exc_info=exc)
        return _body(500, "Внутренняя ошибка сервиса. Попробуйте позже", "internal_error")
