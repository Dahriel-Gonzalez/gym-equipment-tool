"""User ORM model and the Role enum that drives role-based access control."""
from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum as SAEnum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.comment import Comment
    from app.models.issue import Issue


class Role(enum.Enum):
    """Permission tiers

    member  -> log issues, view own
    staff   -> view all, comment/update
    manager -> + resolve/close, manage equipment
    admin   -> full access incl. user management
    """

    member = "member"
    staff = "staff"
    manager = "manager"
    admin = "admin"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A system user."""

    __tablename__ = "users"

    # --- Columns ---
    email: Mapped[str] = mapped_column(
        String(320),  # max practical length of an email address
        unique=True,
        index=True,
        nullable=False,
    )
    # Hash is produced in app/core/security.py; the model only stores it.
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(
        SAEnum(Role, name="user_role"),
        nullable=False,
        default=Role.member,
        server_default=Role.member.value,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    # --- Relationships ---
    # Issue has two FKs back to User (reporter, assignee), so each relationship
    # must name its foreign_keys to disambiguate which column it pairs with.
    reported_issues: Mapped[list["Issue"]] = relationship(
        back_populates="reported_by",
        foreign_keys="Issue.reported_by_id",
    )
    assigned_issues: Mapped[list["Issue"]] = relationship(
        back_populates="assigned_to",
        foreign_keys="Issue.assigned_to_id",
    )
    comments: Mapped[list["Comment"]] = relationship(back_populates="author")

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role.value})>"
