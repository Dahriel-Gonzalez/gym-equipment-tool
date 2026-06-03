"""Password hashing and JWT creation/verification.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

# Token "type" claim values — distinguishes access vs refresh tokens so a refresh
# token can't be replayed as an access token (and vice versa).
ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


# --- Password hashing ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Return a bcrypt hash for storage in User.hashed_password.
    """
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a plaintext password against a stored hash.
    """
    return pwd_context.verify(plain_password, hashed_password)


# --- JWT ---
def _create_token(subject: str, token_type: str, expires_delta: "timedelta") -> str:
    """Build and sign a JWT.
    """

    payload = {
        "sub": str(subject),
        "type": token_type,
        "exp": datetime.now(timezone.utc) + expires_delta,
        "iat": datetime.now(timezone.utc)
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(subject: str | "UUID") -> str:
    """Short-lived token (settings.ACCESS_TOKEN_EXPIRE_MINUTES).
    """

    return _create_token(subject, ACCESS_TOKEN_TYPE, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(subject: str | "UUID") -> str:
    """Long-lived token (settings.REFRESH_TOKEN_EXPIRE_DAYS).
    """

    return _create_token(subject, REFRESH_TOKEN_TYPE, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str, expected_type: str | None = None) -> "dict[str, Any]":
    """Verify signature + expiry and return the claims payload.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
    except JWTError as e:
        raise ValueError("Invalid token") from e

    if expected_type is not None and payload.get("type") != expected_type:
        raise ValueError("Token type mismatch")

    return payload
