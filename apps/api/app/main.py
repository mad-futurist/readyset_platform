import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.rate_limit import InProcessRateLimiter
from app.routes import audit, auth, documents, organizations, people
from app.storage import S3ObjectStorage


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    ensure_bucket = getattr(app.state.storage, "ensure_bucket", None)
    if ensure_bucket:
        await run_in_threadpool(ensure_bucket)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ReadySet API",
        version="1.0.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.storage = S3ObjectStorage(settings)
    app.state.auth_limiter = InProcessRateLimiter()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "X-CSRF-Token",
            "X-ReadySet-Organization",
            "Idempotency-Key",
        ],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

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
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": jsonable_encoder(exc.errors()),
                    "request_id": request.state.request_id,
                }
            },
        )

    @app.get("/healthz", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

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
