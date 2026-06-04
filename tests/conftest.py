"""Shared pytest fixtures.

Tests run against a SEPARATE Postgres database — never the dev/prod one. Create
it once (it just needs to exist; the schema is built per-test here):

    docker compose exec postgres psql -U gym -c "CREATE DATABASE gym_equipment_test;"

The URL defaults to the app's ASYNC_DATABASE_URL with the db name swapped to
gym_equipment_test; override with the TEST_DATABASE_URL env var.

Design:
  - `engine` is FUNCTION-scoped and create_all/drop_all's the schema around each
    test, so every test starts from an empty, isolated database (no cross-test
    bleed, no shared event-loop-scope headaches).
  - `client` overrides the app's get_db to use the test engine.
  - `users` seeds one active user per role; `auth_header(user)` mints a bearer
    token so tests can act as any role.
"""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Callable

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401  — register every table on Base.metadata
from app.config import settings
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import Role, User


def _test_db_url() -> str:
    explicit = os.getenv("TEST_DATABASE_URL")
    if explicit:
        return explicit
    # Swap just the database name in the app's async URL.
    base, _ = settings.ASYNC_DATABASE_URL.rsplit("/", 1)
    return f"{base}/gym_equipment_test"


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """Fresh schema per test: create all tables before, drop all after."""
    eng = create_async_engine(_test_db_url(), poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """A session for tests to seed/inspect data directly (outside the API)."""
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(engine: AsyncEngine) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client wired to the app, with get_db pointed at the test engine."""
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def users(db_session: AsyncSession) -> dict[Role, User]:
    """One active, seeded user per role. Password is always 'password123'."""
    seeded: dict[Role, User] = {}
    for role in Role:
        user = User(
            email=f"{role.value}@test.com",
            full_name=f"{role.value.title()} User",
            hashed_password=hash_password("password123"),
            role=role,
            is_active=True,
        )
        db_session.add(user)
        seeded[role] = user
    await db_session.commit()
    for user in seeded.values():
        await db_session.refresh(user)
    return seeded


@pytest.fixture
def auth_header() -> Callable[[User], dict[str, str]]:
    """Factory: auth_header(user) -> the Authorization header for that user."""

    def _make(user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}

    return _make
