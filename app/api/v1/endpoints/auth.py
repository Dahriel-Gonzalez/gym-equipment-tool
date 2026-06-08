"""Authentication endpoints: register, login, refresh, logout.

Thin HTTP layer — it validates input (via schemas), calls crud + security, and
maps domain errors to status codes. No business logic or raw queries live here.
Mounted under /auth by app/api/v1/router.py (which supplies the prefix + tag).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import LOGIN_LIMIT, REGISTER_LIMIT, REFRESH_LIMIT, limiter
from app.core.security import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.crud import user as user_crud
from app.db.session import get_db
from app.schemas.token import RefreshRequest, Token
from app.schemas.user import UserCreate, UserResponse

router = APIRouter()


def _tokens_for(user_id: UUID) -> Token:
    """Mint a fresh access + refresh pair for a user id."""
    return Token(
        access_token=create_access_token(str(user_id)),
        refresh_token=create_refresh_token(str(user_id)),
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(REGISTER_LIMIT)
async def register(
    request: Request, payload: UserCreate, db: AsyncSession = Depends(get_db)
) -> UserResponse:
    """Create a new member account. Returns the created user (no token)."""
    try:
        user = await user_crud.create(db, payload)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="EMAIL_ALREADY_REGISTERED"
        ) from exc
    return user


@router.post("/login", response_model=Token)
@limiter.limit(LOGIN_LIMIT)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> Token:
    """Exchange email + password for an access + refresh token pair."""
    # OAuth2 form field is `username`; we use it as the email.
    user = await user_crud.get_by_email(db, form_data.username)
    # Identical error for "no such email" and "wrong password" — don't reveal
    # which accounts exist.
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="INVALID_CREDENTIALS")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="INACTIVE_USER")
    return _tokens_for(user.id)


@router.post("/refresh", response_model=Token)
@limiter.limit(REFRESH_LIMIT)
async def refresh(
    request: Request, payload: RefreshRequest, db: AsyncSession = Depends(get_db)
) -> Token:
    """Exchange a valid refresh token for a new token pair."""
    try:
        claims = decode_token(payload.refresh_token, expected_type=REFRESH_TOKEN_TYPE)
        user_id = UUID(claims["sub"])
    except (ValueError, KeyError) as exc:
        # Bad signature, expired, wrong type, or malformed/absent `sub`.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="INVALID_TOKEN") from exc

    user = await user_crud.get(db, user_id)
    if user is None or not user.is_active:
        # Token was valid but the account is gone/deactivated.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="INVALID_TOKEN")
    return _tokens_for(user.id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: RefreshRequest) -> None:
    """Log out the current refresh token.

    Revocation isn't implemented yet, so this is a no-op endpoint until then.
    """
    return None
