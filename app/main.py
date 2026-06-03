"""FastAPI application entrypoint: app instance, router mounting, health check."""
from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import text

from app.api.v1.router import api_router
from app.config import settings
from app.db.session import engine

app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
    # Versioned API; the interactive docs are at /docs and /redoc.
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
