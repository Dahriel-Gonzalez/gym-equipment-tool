"""Shared FastAPI dependencies: current-user resolution and role gating.

These are the seams every protected endpoint reuses. `get_current_user` answers
"who is this request?" (authentication); `require_role` answers "are they allowed?"
(authorization). Keeping both here means endpoints stay declarative:

    @router.post("/equipment")
    async def create_equipment(
        ...,
        current_user: User = Depends(require_role(Role.manager, Role.admin)),
    ): ...
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import ACCESS_TOKEN_TYPE, decode_token
from app.crud import user as user_crud
from app.db.session import get_db
from app.models.user import Role, User

# Extracts the bearer token from the Authorization header. tokenUrl must point at
# the login route so Swagger's "Authorize" button knows where to get a token.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the authenticated user from a Bearer access token, or 401.

    One opaque error for every failure mode (missing claim, bad signature,
    expired, wrong token type, unknown or deactivated user) so we never leak
    which part failed.

    Side effect: stashes the resolved user id on request.state so the per-user
    rate limiter (user_key) can bucket by user. This runs during dependency
    resolution, before the @limiter.limit check inside the route body.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="INVALID_TOKEN",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # expected_type guards against a refresh token being used as an access token.
        claims = decode_token(token, expected_type=ACCESS_TOKEN_TYPE)
        user_id = UUID(claims["sub"])
    except (ValueError, KeyError):
        raise credentials_exception

    user = await user_crud.get(db, user_id)
    if user is None or not user.is_active:
        raise credentials_exception
    request.state.current_user_id = user.id
    return user


def require_role(*roles: Role) -> Callable[..., Awaitable[User]]:
    """Build a dependency that allows only the given roles, else 403.

    This is a FACTORY: calling it returns a fresh dependency that closes over
    `roles`. The returned checker depends on get_current_user, so authentication
    runs first; if the role isn't permitted it raises 403 (authenticated, but not
    authorized). It returns the user so endpoints can both gate AND grab the user
    in one `Depends`.

    Note: membership is checked against the EXACT set passed — there's no implicit
    hierarchy. "manager+" means you pass both: require_role(Role.manager, Role.admin).
    """

    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="INSUFFICIENT_PERMISSIONS",
            )
        return current_user

    return role_checker
