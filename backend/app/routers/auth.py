from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Request, Response
from pydantic import BaseModel, Field

from .. import config
from ..errors import ApiError
from ..services.security import hash_password, opaque_token, token_digest, verify_password

router = APIRouter(prefix="/auth")
_COOKIE_NAME = "tram_session"


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


def require_session(request: Request, tram_session: str | None = Cookie(None)) -> None:
    """Protect every data endpoint; health is public for container orchestration."""
    if request.url.path.endswith("/health"):
        return
    database = getattr(request.app.state, "database", None)
    if database is None:  # direct pytest/dev runs without DATABASE_URL
        return
    if not tram_session or not database.session_user(token_digest(tram_session)):
        raise ApiError(401, "Сеанс завершён. Войдите в систему заново.", "unauthorized")


@router.post("/login", summary="Войти в систему")
def login(body: LoginBody, request: Request, response: Response):
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise ApiError(503, "Авторизация доступна после подключения PostgreSQL", "auth_unavailable")

    user = database.get_user(body.username)
    valid = bool(user and verify_password(body.password, user["password_hash"]))
    if not valid:
        # Keep the invalid-credential response identical for unknown users and wrong passwords.
        if user is None:
            verify_password(body.password, hash_password("invalid-user-timing-equalizer"))
        raise ApiError(401, "Неверный логин или пароль", "invalid_credentials")

    token = opaque_token()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=config.AUTH_SESSION_HOURS)
    database.create_session(body.username, token_digest(token), now, expires)
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        max_age=config.AUTH_SESSION_HOURS * 60 * 60,
        expires=expires,
        httponly=True,
        secure=config.AUTH_COOKIE_SECURE,
        samesite="strict",
        path=config.AUTH_COOKIE_PATH,
    )
    return {"username": body.username, "expires_at": expires.isoformat()}


@router.get("/me", summary="Текущий пользователь")
def me(request: Request, tram_session: str | None = Cookie(None)):
    database = getattr(request.app.state, "database", None)
    if database is None or not tram_session:
        raise ApiError(401, "Войдите в систему", "unauthorized")
    username = database.session_user(token_digest(tram_session))
    if not username:
        raise ApiError(401, "Сеанс завершён. Войдите в систему заново.", "unauthorized")
    return {"username": username}


@router.post("/logout", summary="Выйти из системы")
def logout(request: Request, response: Response, tram_session: str | None = Cookie(None)):
    database = getattr(request.app.state, "database", None)
    if database is not None and tram_session:
        database.delete_session(token_digest(tram_session))
    response.delete_cookie(key=_COOKIE_NAME, path=config.AUTH_COOKIE_PATH, httponly=True, secure=config.AUTH_COOKIE_SECURE, samesite="strict")
    return {"status": "ok"}
