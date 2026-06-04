"""Pydantic v2 schemas for issue comments."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.user import UserSummary


class CommentCreate(BaseModel):
    """POST /issues/{id}/comments — add a comment.

    `is_internal` is accepted but POLICY-GATED in the endpoint: only staff+ may
    set it True (members can't create staff-only notes). The schema can't enforce
    that — it depends on the caller's role — so it just defaults to False and the
    endpoint rejects/forces it for members.
    """

    body: str = Field(..., min_length=1, max_length=5000)
    is_internal: bool = False


class CommentUpdate(BaseModel):
    """PATCH /issues/{id}/comments/{cid} — edit a comment's text.

    Only the body is editable. is_internal isn't changed here (re-classifying a
    note is a different, role-sensitive action); author/equipment/issue are fixed.
    """

    body: str = Field(..., min_length=1, max_length=5000)


class CommentResponse(BaseModel):
    """A comment as returned by the API. Internal comments are filtered out for
    members upstream (in the endpoint), so reaching this schema already implies
    the caller is allowed to see it."""

    id: UUID
    issue_id: UUID
    body: str
    is_internal: bool
    author: UserSummary
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
