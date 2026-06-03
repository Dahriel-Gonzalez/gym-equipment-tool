"""Token schemas: auth responses and the refresh/logout request body."""
from __future__ import annotations

from pydantic import BaseModel


class Token(BaseModel):
    """Returned by /auth/login and /auth/refresh.
    """

    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    """Body for /auth/refresh (and /auth/logout): the refresh token to act on."""

    refresh_token: str
