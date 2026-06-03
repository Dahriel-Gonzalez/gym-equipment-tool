"""Pydantic v2 schemas for equipment.

Same per-operation split as users: Base holds the fields common to input AND
output; Create/Update/Response/Summary specialize from there.
"""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.equipment import EquipmentStatus


class EquipmentBase(BaseModel):
    """Descriptive fields shared by input and output, with the same shape."""

    name: str = Field(..., min_length=1, max_length=255)        # e.g. "Treadmill #3"
    category: str = Field(..., min_length=1, max_length=100)    # e.g. "Cardio"
    location: str = Field(..., min_length=1, max_length=100)    # e.g. "Zone A"
    serial_number: str | None = Field(None, max_length=100)     # unique, optional
    purchased_at: date | None = None


class EquipmentCreate(EquipmentBase):
    """POST /equipment — add a new asset (manager+).

    `status` is settable at creation but defaults to operational, so a manager
    can register something already under maintenance without a second call.
    """

    status: EquipmentStatus = EquipmentStatus.operational


class EquipmentUpdate(BaseModel):
    """PATCH /equipment/{id} — partial update, every field optional.

    Standalone (not EquipmentBase) because base's name/category/location are
    required; a PATCH must allow omitting them.
    """

    name: str | None = Field(None, min_length=1, max_length=255)
    category: str | None = Field(None, min_length=1, max_length=100)
    location: str | None = Field(None, min_length=1, max_length=100)
    serial_number: str | None = Field(None, max_length=100)
    status: EquipmentStatus | None = None
    purchased_at: date | None = None


class EquipmentSummary(BaseModel):
    """Slim nested form (id + name) embedded in other responses,
    e.g. IssueResponse.equipment. Avoids dragging the full record around."""

    id: UUID
    name: str

    model_config = ConfigDict(from_attributes=True)


class EquipmentResponse(EquipmentBase):
    """Full equipment record as returned by the API."""

    id: UUID
    status: EquipmentStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
