"""Startup data seeding.

Currently just the first admin: the role system is bootstrap-proof only if at
least one admin exists, but registration always creates a `member` and only an
admin can promote others — a chicken-and-egg. Seeding the configured admin on
startup breaks that cycle so a fresh database is immediately usable.
"""
from __future__ import annotations

from app.config import settings
from app.core.logging import logger
from app.core.security import hash_password
from app.crud import user as user_crud
from app.models.user import Role, User
from sqlalchemy.ext.asyncio import AsyncSession

# Obvious placeholder passwords we don't want silently shipped to a real deploy.
_PLACEHOLDER_PASSWORDS = {"change-me", "changeme", "password", ""}


async def seed_first_admin(db: AsyncSession) -> User | None:
    """Create the configured admin (FIRST_ADMIN_EMAIL/PASSWORD) if no user with
    that email exists. Returns the new user, or None if it was already present.

    Idempotent: keyed on the email, so running it on every startup is safe — once
    the admin exists this is a single SELECT and a no-op.
    """
    existing = await user_crud.get_by_email(db, settings.FIRST_ADMIN_EMAIL)
    if existing is not None:
        return None

    if settings.FIRST_ADMIN_PASSWORD in _PLACEHOLDER_PASSWORDS:
        # Seed anyway (dev convenience) but make the weak credential loud.
        logger.warning("admin_seed_placeholder_password", email=settings.FIRST_ADMIN_EMAIL)

    admin = User(
        email=settings.FIRST_ADMIN_EMAIL,
        full_name="Administrator",
        hashed_password=hash_password(settings.FIRST_ADMIN_PASSWORD),
        role=Role.admin,
        is_active=True,
    )
    db.add(admin)
    await db.commit()
    await db.refresh(admin)
    logger.info("admin_seeded", email=settings.FIRST_ADMIN_EMAIL)
    return admin
