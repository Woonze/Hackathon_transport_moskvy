from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .errors import install_error_handlers
from .routers import auth, data, dispatch, ingest, live, scenarios, stops
from .services.database import Database
from .store import DataStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tram")


@asynccontextmanager
async def lifespan(app: FastAPI):
    started = time.perf_counter()
    app.state.database = None
    if config.DATABASE_URL:
        database = Database(config.DATABASE_URL)
        database.open()
        database.ensure_user(config.AUTH_USERNAME, config.AUTH_PASSWORD_HASH or "")
        app.state.database = database
        log.info("PostgreSQL подключён")
    else:
        log.warning("DATABASE_URL не задан: запускается локальный режим без PostgreSQL и авторизации")
    app.state.store = DataStore(database=app.state.database)
    log.info("Данные загружены за %.2f с", time.perf_counter() - started)
    if not config.INGEST_API_KEY:
        log.warning("INGEST_API_KEY не задан: приём данных открыт без ключа (допустимо только для разработки)")
    try:
        yield
    finally:
        if app.state.database:
            app.state.database.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Прогноз пассажиропотока трамваев Москвы",
        version=config.API_VERSION,
        description="Прогноз посадок по маршруту, дате и часу, история, агрегации и выгрузка.",
        root_path=os.getenv("APP_ROOT_PATH", ""),
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
    )

    @app.middleware("http")
    async def no_cache_frontend_entry(request: Request, call_next):
        if request.url.path == "/" or request.url.path.endswith(".html"):
            # A rebuilt frontend can have the same index size and filesystem timestamp
            # inside a replacement container. Never let a validator reuse stale asset names.
            request.scope["headers"] = [
                (name, value)
                for name, value in request.scope["headers"]
                if name.lower() not in (b"if-none-match", b"if-modified-since")
            ]
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response
        return await call_next(request)

    @app.middleware("http")
    async def timing(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Process-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
        return response

    install_error_handlers(app)
    def sync_store(request: Request) -> None:
        request.app.state.store.refresh()  # подхватываем данные, принятые другим воркером

    for prefix in ("/api/v1", "/api"):
        app.include_router(auth.router, prefix=prefix, tags=["auth"])

    for router in (data.router, scenarios.router, ingest.router, stops.router, live.router, dispatch.router):
        dependencies = [Depends(sync_store), Depends(auth.require_session)]
        app.include_router(router, prefix="/api/v1", tags=["v1"], dependencies=dependencies)
        app.include_router(router, prefix="/api", include_in_schema=False, dependencies=dependencies)  # алиасы

    if config.FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=config.FRONTEND_DIST, html=True), name="frontend")
    return app


app = create_app()
