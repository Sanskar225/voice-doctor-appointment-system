"""FastAPI application factory with explicit DI container, request correlation, and domain errors."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.container import AppContainer
from .api.routes_clinic import router as clinic_router
from .api.routes_events import router as events_router
from .api.routes_voice import router as voice_router
from .config import Settings, get_settings
from .domain.exceptions import DomainError
from .logging_config import configure_logging

logger = logging.getLogger("aurelia.app")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    container = AppContainer.build(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container
        container.db.initialize(force_reset=False)
        logger.info(
            "Aurelia Health API ready | db=%s | llm=%s | voice_ready=%s",
            container.db.db_path,
            resolved_settings.gemini_model,
            resolved_settings.voice_ready,
        )
        yield
        logger.info("Aurelia Health API shutting down")

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )
    app.state.container = container

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_correlation_middleware(request: Request, call_next) -> Response:
        req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        started = time.perf_counter()
        response: Response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        response.headers["X-Request-ID"] = req_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if not request.url.path.endswith("/events"):
            logger.debug(
                "%s %s -> %d (%.1fms) req=%s",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
                req_id,
            )
        return response

    @app.exception_handler(DomainError)
    async def handle_domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        body: dict[str, object] = {"code": exc.code, "detail": exc.message}
        if exc.details:
            body["details"] = exc.details
        return JSONResponse(status_code=exc.http_status, content=body)

    app.include_router(clinic_router)
    app.include_router(events_router)
    app.include_router(voice_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    cfg = get_settings()
    uvicorn.run("app.main:app", host=cfg.host, port=cfg.port, reload=True)
