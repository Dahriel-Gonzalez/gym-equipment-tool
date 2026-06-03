"""Equipment ORM model and the Status enum that defines the possible statuses."""
from __future__ import annotations

from datetime import date
import enum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, Enum as SAEnum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin

if TYPE_CHECKING:
    from app.models.issue import Issue


class EquipmentStatus(enum.Enum):
    """Equipment Status types

    operational  -> no issues
    under_maintenance   -> equipment with active issues
    decommissioned -> displayed to staff but not members, cannot log issues
    """

    operational = "operational"
    under_maintenance = "under_maintenance"
    decommissioned = "decommissioned"

class Equipment(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Equipment model."""

    __tablename__ = "equipment"

    # --- Columns ---
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    serial_number: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    status: Mapped[EquipmentStatus] = mapped_column(
        SAEnum(EquipmentStatus, name="equipment_status"),
        nullable=False,
        default=EquipmentStatus.operational,
        server_default=EquipmentStatus.operational.value,
    )
    purchased_at: Mapped[date | None] = mapped_column(Date, nullable=True)


    # --- Relationships ---
    '''Every issue must be linked to an equipment, but we want to allow equipment to exist without issues.'''
    equipment_issues: Mapped[list["Issue"]] = relationship(
        back_populates="equipment",
        foreign_keys="Issue.equipment_id",
    )

    def __repr__(self) -> str:
        return f"<Equipment {self.name} ({self.status.value})>"
