"""Async database engine, session factory, and the get_db dependency.

This is the only module that owns the engine. Endpoints never touch it
directly — they depend on get_db(), which hands out a per-request session.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings


# --- Engine ---
# Managed Postgres (Neon) requires TLS; asyncpg enables it via connect_args, not
# the sslmode query param (which config.py strips off the URL).
connect_args = {"ssl": True} if settings.db_ssl_required else {}

engine = create_async_engine(
    settings.ASYNC_DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    connect_args=connect_args,
)


# --- Session factory ---
SessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,  # keep ORM objects usable after commit for response serialization
)

# --- Dependency ---
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a session per request; always close it, roll back on error."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
