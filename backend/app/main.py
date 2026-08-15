import time
import uuid

import structlog
from asyncpg import PostgresError
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1 import router as api_v1_router
from app.core.config import get_settings
from app.core.database import engine
from app.core.errors import AppError


settings = get_settings()
logger = structlog.get_logger()
app = FastAPI(
    title="Karunya Sparsham API",
    version="1.0.0",
    docs_url="/docs" if settings.APP_ENV != "production" else None,
    redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(origin).rstrip("/") for origin in settings.ALLOWED_ORIGINS],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-CSRF-Token"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_completed",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "field_errors": exc.field_errors,
            },
            "meta": {"request_id": getattr(request.state, "request_id", None)},
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed.",
                "field_errors": {"errors": exc.errors()},
            },
            "meta": {"request_id": getattr(request.state, "request_id", None)},
        },
    )


@app.exception_handler(SQLAlchemyError)
@app.exception_handler(PostgresError)
async def database_error_handler(request: Request, exc: SQLAlchemyError | PostgresError):
    logger.error(
        "database_error",
        request_id=getattr(request.state, "request_id", None),
        error_type=type(exc).__name__,
        error=str(exc),
    )
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "DATABASE_UNAVAILABLE",
                "message": "The database is temporarily unavailable.",
                "field_errors": {},
            },
            "meta": {"request_id": getattr(request.state, "request_id", None)},
        },
    )


@app.get("/health/live", include_in_schema=False)
async def health_live():
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def health_ready():
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        logger.warning("readiness_database_unavailable")
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "database": "unavailable"},
        )
    return {"status": "ready", "database": "ok"}


app.include_router(api_v1_router, prefix="/api/v1")
