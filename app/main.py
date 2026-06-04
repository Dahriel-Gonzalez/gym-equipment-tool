"""FastAPI application entrypoint: app instance, router mounting, health check."""
from __future__ import annotations

import time
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.config import settings
from app.core.errors import HUMAN_MESSAGES, INTERNAL_ERROR, VALIDATION_ERROR
from app.core.logging import configure_logging, logger
from app.db.session import engine

# Configure logging before anything emits a log line.
configure_logging(debug=settings.DEBUG)

app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
    # Versioned API; the interactive docs are at /docs and /redoc.
)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Bind a per-request id (and method/path) into the log context, time the
    request, and echo the id back in the X-Request-ID header.

    request_id is taken from an inbound X-Request-ID header if present (so it can
    be traced across services), otherwise generated.
    """
    structlog.contextvars.clear_contextvars()
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    structlog.contextvars.bind_contextvars(
        request_id=request_id, method=request.method, path=request.url.path
    )
    start = time.perf_counter()
    # If call_next raises (unhandled), the 500 handler logs + responds; we leave
    # the contextvars bound so it can read request_id (next request clears them).
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info("request_completed", status_code=response.status_code, duration_ms=duration_ms)
    response.headers["X-Request-ID"] = request_id
    return response


# --- Centralized error envelope ---
# Every error response has the same shape: {"error": <CODE>, "message": <sentence>}
# (validation errors add a "detail" with the field-level breakdown). Clients can
# always branch on `error`; humans read `message`.


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Render HTTPExceptions as the standard envelope.

    `exc.detail` is our machine-readable CODE (e.g. ISSUE_NOT_FOUND); we map it to
    a human message. Handling the Starlette base class also catches framework
    errors like a 404 for an unknown route.
    """
    code = exc.detail if isinstance(exc.detail, str) else "ERROR"
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": code, "message": HUMAN_MESSAGES.get(code, code)},
        headers=getattr(exc, "headers", None),  # preserve WWW-Authenticate on 401s
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422s from request validation, in the same envelope plus a field breakdown."""
    return JSONResponse(
        status_code=422,
        content={
            "error": VALIDATION_ERROR,
            "message": HUMAN_MESSAGES[VALIDATION_ERROR],
            "detail": jsonable_encoder(exc.errors()),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last resort for uncaught exceptions: log the full traceback (with the
    bound request_id) and return a sanitized 500 — never leak internals."""
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    logger.exception("unhandled_exception")  # exc_info captured automatically
    return JSONResponse(
        status_code=500,
        content={"error": INTERNAL_ERROR, "message": HUMAN_MESSAGES[INTERNAL_ERROR]},
        headers={"X-Request-ID": request_id} if request_id else None,
    )


# All v1 routes live under /api/v1 (e.g. POST /api/v1/auth/register).
app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
async def health() -> dict[str, object]:
    """Liveness + database connectivity probe.

    Runs a trivial `SELECT 1` so the check fails if Postgres is unreachable —
    more useful than a static 200 that's green even when the DB is down.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}
