"""Tests for the first-admin startup seeder."""
from __future__ import annotations

from app.config import settings
from app.crud import user as user_crud
from app.db.seed import seed_first_admin
from app.models.user import Role


async def test_seed_creates_admin(db_session):
    created = await seed_first_admin(db_session)
    assert created is not None
    assert created.email == settings.FIRST_ADMIN_EMAIL
    assert created.role == Role.admin
    assert created.is_active is True

    # And it's actually persisted/findable.
    fetched = await user_crud.get_by_email(db_session, settings.FIRST_ADMIN_EMAIL)
    assert fetched is not None and fetched.role == Role.admin


async def test_seed_is_idempotent(db_session):
    first = await seed_first_admin(db_session)
    assert first is not None
    # Second run finds the existing admin and does nothing.
    second = await seed_first_admin(db_session)
    assert second is None
