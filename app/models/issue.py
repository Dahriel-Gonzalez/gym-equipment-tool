"""Issue ORM model plus the severity and status enums for an equipment issue."""
from __future__ import annotations

from datetime import datetime
import enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.comment import Comment
    from app.models.equipment import Equipment
    from app.models.user import User


class IssueSeverity(enum.Enum):
    """Issue Severity types

    low -> minor issue
    medium -> moderate issue
    high -> serious issue
    critical -> urgent issue requiring immediate attention
    """

    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"

class IssueStatus(enum.Enum):
    """Issue Status types

    open -> issue is active and unresolved
    in_progress -> staff are working on the issue
    resolved -> issue resolved by staff but not yet closed by manager/admin
    closed -> issue is fully resolved and closed by manager/admin
    """

    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    closed = "closed"

class Issue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Issue model."""

    __tablename__ = "issues"

    # --- Columns ---
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[IssueSeverity] = mapped_column(
        SAEnum(IssueSeverity, name="issue_severity"),
        nullable=False,
        default=IssueSeverity.low,
    )
    status: Mapped[IssueStatus] = mapped_column(
        SAEnum(IssueStatus, name="issue_status"),
        nullable=False,
        default=IssueStatus.open,
        server_default=IssueStatus.open.value,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Foreign keys ---
    # An issue is always about a piece of equipment, by a reporter -> required.
    equipment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("equipment.id"),
        nullable=False,
        index=True,
    )
    reported_by_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    # Assigned later (or never) / only set once resolved -> nullable.
    assigned_to_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    resolved_by_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )

    # --- Relationships ---
    # Single FK to equipment -> no disambiguation needed.
    equipment: Mapped["Equipment"] = relationship(back_populates="equipment_issues")

    # Three relationships target `users`, so each must name its foreign_keys.
    reported_by: Mapped["User"] = relationship(
        back_populates="reported_issues",
        foreign_keys=[reported_by_id],
    )
    assigned_to: Mapped["User | None"] = relationship(
        back_populates="assigned_issues",
        foreign_keys=[assigned_to_id],
    )
    # No inverse collection on User, so this one is one-directional.
    resolved_by: Mapped["User | None"] = relationship(foreign_keys=[resolved_by_id])

    # One issue -> many comments; deleting the issue removes its comments.
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="issue",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Issue {self.title} ({self.status.value})>"
