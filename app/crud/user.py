"""CRUD (data-access) layer for User.

Commit policy: get_db() yields a session but does not commit, so the write
helpers here commit explicitly.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import Role, User
from app.schemas.user import UserCreate, UserUpdate


async def get(db: "AsyncSession", user_id: "UUID") -> "User | None":
    """Fetch one user by primary key, or None.
    """

    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    """Fetch one user by email, or None.
    """

    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create(db: AsyncSession, user_in: UserCreate) -> User:
      """Insert a new user. Raises ValueError if the email is already taken."""
      
      if await get_by_email(db, user_in.email) is not None:
          raise ValueError("Email already registered")

      user = User(
          email=user_in.email,
          full_name=user_in.full_name,
          hashed_password=hash_password(user_in.password),
      )
      db.add(user)

      try:
          await db.commit()
      except IntegrityError as exc:
          await db.rollback()
          raise ValueError("Email already registered") from exc
      await db.refresh(user)
      return user


async def update(db: "AsyncSession", user: "User", user_in: "UserUpdate") -> "User":
    """Apply a partial update to an existing, already-loaded user.
    """

    data = user_in.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return user


async def get_multi(
    db: AsyncSession, *, skip: int = 0, limit: int = 20
) -> tuple[list[User], int]:
    """Return a page of users AND the total count of all users.

    `total` runs a COUNT over the same base query (no offset/limit) so the
    response envelope can report has_next. Ordered by created_at + id for
    stable paging.
    """
    base = select(User)
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = await db.execute(
        base.order_by(User.created_at, User.id).offset(skip).limit(limit)
    )
    return list(rows.scalars().all()), total


async def set_role(db: AsyncSession, user: User, role: Role) -> User:
    """Set a user's role (admin action). `user` must already be loaded."""
    user.role = role
    await db.commit()
    await db.refresh(user)
    return user


async def set_password(db: AsyncSession, user: User, hashed_password: str) -> None:
    """Store an already-hashed password. Hashing stays in the caller so this
    layer never sees plaintext."""
    user.hashed_password = hashed_password
    await db.commit()


async def deactivate(db: AsyncSession, user: User) -> User:
    """Soft-delete: flip is_active to False. The row stays for audit/history;
    queries that should hide inactive users filter on is_active themselves."""
    user.is_active = False
    await db.commit()
    await db.refresh(user)
    return user

