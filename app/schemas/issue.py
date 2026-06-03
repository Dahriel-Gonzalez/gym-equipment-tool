"""Pydantic v2 schemas for issues.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.issue import IssueSeverity, IssueStatus
from app.schemas.equipment import EquipmentSummary
from app.schemas.user import UserSummary


class IssueCreate(BaseModel):
    """POST /issues — log a new issue.

    Only equipment + the descriptive fields. `reported_by` is the current user
    (set server-side, never trusted from the client) and `status` always starts
    at `open` (model default) — neither is accepted here.
    """

    equipment_id: UUID
    title: str = Field(..., min_length=5, max_length=200)
    description: str = Field(..., min_length=10)
    severity: IssueSeverity = IssueSeverity.medium


class IssueUpdate(BaseModel):
    """PATCH /issues/{id} — edit descriptive fields only (partial).

    Status, assignment, and equipment are intentionally absent: status has its
    own transition-validated endpoint, assignment is a separate action, and an
    issue can't be moved to different equipment.
    """

    title: str | None = Field(None, min_length=5, max_length=200)
    description: str | None = Field(None, min_length=10)
    severity: IssueSeverity | None = None


class IssueStatusUpdate(BaseModel):
    """PATCH /issues/{id}/status — request a status transition.

    `note` is an optional comment recorded alongside the change. 
    """

    status: IssueStatus
    note: str | None = None


class IssueAssign(BaseModel):
    """PATCH /issues/{id}/assign — assign the issue to a staff member."""

    assigned_to_id: UUID


class IssueResponse(BaseModel):
    """Full issue as returned by the API — relations as slim nested summaries."""

    id: UUID
    title: str
    description: str
    severity: IssueSeverity
    status: IssueStatus
    equipment: EquipmentSummary
    reported_by: UserSummary
    assigned_to: UserSummary | None
    resolved_at: datetime | None
    resolved_by: UserSummary | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
