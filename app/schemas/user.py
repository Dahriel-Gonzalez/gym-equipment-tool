"""Pydantic v2 schemas for users.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import Role

# bcrypt (used in app/core/security.py) silently truncates at 72 BYTES, so we cap
# here at the edge.
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 72


class UserBase(BaseModel):
    """The fields common to BOTH input and output.
    """
    email: str = Field(..., min_length=1, max_length=320)
    full_name: str = Field(..., min_length=1, max_length=255)


class UserCreate(UserBase):
    """Registration payload.
    """

    password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class UserUpdate(BaseModel):
    """PATCH /users/me — update name only could include other nonsensitive fields any member can change.
    """

    full_name: str | None = Field(None, min_length=1, max_length=255)


class PasswordChange(BaseModel):
    """Body for POST /users/me/password — a self-service password change.
    """

    current_password: str
    new_password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class UserSummary(BaseModel):
    """Slim nested form (id + name) for embedding in other responses
    """

    id: UUID
    full_name: str

    model_config = ConfigDict(from_attributes=True)


class UserResponse(UserBase):
    """Full user as returned by the API except hashed_password.
    """

    id: UUID
    role: Role
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
