import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.database import engine
from app.email import create_email_sender
from app.file_security import create_file_scanner
from app.rate_limit import create_rate_limiter
from app.routes import audit, auth, documents, organizations, people
from app.storage import ObjectNotFound, S3ObjectStorage, StorageError


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    ensure_bucket = getattr(app.state.storage, "ensure_bucket", None)
    if ensure_bucket:
        await run_in_threadpool(ensure_bucket)
    yield


logger = logging.getLogger("readyset.request")


def _request_log(payload: dict[str, object], *, structured: bool) -> None:
    if structured:
        logger.info(json.dumps(payload, separators=(",", ":"), default=str))
    else:
        logger.info(
            "%s %s %s %.1fms request_id=%s",
            payload["method"], payload["path"], payload["status"], payload["latency_ms"],
            payload["request_id"],
        )


def _configure_request_logging(*, structured: bool) -> None:
    logger.setLevel(logging.INFO)
    if structured:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.handlers[:] = [handler]
        logger.propagate = False


def create_app() -> FastAPI:
    settings = get_settings()
    _configure_request_logging(structured=settings.is_hardened)
    app = FastAPI(
        title="ReadySet API",
        version="1.0.0",
        docs_url=None if settings.is_hardened else "/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.storage = S3ObjectStorage(settings)
    app.state.settings = settings
    app.state.email_sender = create_email_sender(settings)
    app.state.rate_limiter = create_rate_limiter(settings)
    app.state.file_scanner = create_file_scanner(settings)
    app.state.database_engine = engine
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "X-CSRF-Token",
            "X-ReadySet-Organization",
        ],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        supplied_request_id = request.headers.get("X-Request-ID", "")
        request.state.request_id = (
            supplied_request_id
            if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", supplied_request_id)
            else str(uuid.uuid4())
        )
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request.state.request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "same-origin"
            return response
        except StorageError as exc:
            status_code = 404 if isinstance(exc, ObjectNotFound) else 503
            raise
        finally:
            payload: dict[str, object] = {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": "info",
                "request_id": request.state.request_id,
                "method": request.method,
                "path": request.url.path,
                "status": status_code,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }
            for field in ("user_id", "organization_id"):
                if value := getattr(request.state, field, None):
                    payload[field] = str(value)
            _request_log(payload, structured=settings.is_hardened)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc):  # type: ignore[no-untyped-def]
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": f"http_{exc.status_code}",
                    "message": str(exc.detail),
                    "request_id": request.state.request_id,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        safe_details = [
            {key: value for key, value in error.items() if key not in {"input", "ctx"}}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": jsonable_encoder(safe_details),
                    "request_id": request.state.request_id,
                }
            },
        )

    @app.exception_handler(StorageError)
    async def storage_error(request: Request, exc: StorageError) -> JSONResponse:
        request_id_value = getattr(request.state, "request_id", str(uuid.uuid4()))
        missing = isinstance(exc, ObjectNotFound)
        return JSONResponse(
            status_code=404 if missing else 503,
            content={
                "error": {
                    "code": "object_not_found" if missing else "storage_unavailable",
                    "message": "Object not found" if missing else "Storage is temporarily unavailable",
                    "request_id": request_id_value,
                }
            },
            headers={
                "X-Request-ID": request_id_value,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "same-origin",
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        request_id_value = getattr(request.state, "request_id", str(uuid.uuid4()))
        logger.exception("Unhandled request failure request_id=%s", request_id_value, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Internal server error",
                    "request_id": request_id_value,
                }
            },
            headers={
                "X-Request-ID": request_id_value,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "same-origin",
            },
        )

    @app.get("/livez", tags=["system"])
    @app.get("/healthz", tags=["system"], include_in_schema=False)
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["system"])
    def ready(request: Request) -> JSONResponse:
        try:
            with request.app.state.database_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            request.app.state.storage.check_access()
            request.app.state.rate_limiter.check_available()
            if settings.uploads_enabled:
                request.app.state.file_scanner.check_available()
        except Exception:
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return JSONResponse(content={"status": "ready"})

    for router in (
        auth.router,
        organizations.router,
        people.router,
        documents.router,
        audit.router,
    ):
        app.include_router(router, prefix="/api/v1")
    return app


# Kept as an importable ASGI object for Uvicorn.
app = create_app()
