"""User endpoints: self-service profile + admin/manager user management.

Three access tiers, enforced via dependencies:
  - /me*              any authenticated user (get_current_user)
  - GET /{id}         manager+        (require_role(manager, admin))
  - list / role / delete   admin only (require_role(admin))

ROUTE ORDER MATTERS: the literal /me paths are declared BEFORE /{user_id} so
"me" is never parsed as a user_id path param. FastAPI matches in definition order.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.crud import user as user_crud
from app.db.session import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import Role, User
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.schemas.user import PasswordChange, RoleUpdate, UserResponse, UserUpdate

router = APIRouter()


# --- Self-service (any authenticated user) ---

@router.get("/me", response_model=UserResponse)
async def read_me(current_user: User = Depends(get_current_user)) -> User:
    """Return the caller's own profile. No DB hit — the dependency already
    loaded the user."""
    return current_user


@router.patch("/me", response_model=UserResponse)
async def update_me(
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Update the caller's own profile (currently full_name only)."""
    return await user_crud.update(db, current_user, payload)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_my_password(
    payload: PasswordChange,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Self-service password change. Re-authenticates with the current password
    before accepting the new one."""
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="INVALID_CREDENTIALS")
    await user_crud.set_password(db, current_user, hash_password(payload.new_password))
    return None


# --- Management (manager+ / admin) ---

@router.get("/", response_model=PaginatedResponse[UserResponse])
async def list_users(
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role(Role.admin)),
) -> PaginatedResponse[UserResponse]:
    """List all users (admin only). Offset/limit paginated."""
    users, total = await user_crud.get_multi(
        db, skip=pagination.skip, limit=pagination.limit
    )
    return PaginatedResponse.create(
        users, total, skip=pagination.skip, limit=pagination.limit
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    _mgr: User = Depends(require_role(Role.manager, Role.admin)),
) -> User:
    """Fetch any user by id (manager+)."""
    user = await user_crud.get(db, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="USER_NOT_FOUND")
    return user


@router.patch("/{user_id}/role", response_model=UserResponse)
async def change_user_role(
    user_id: UUID,
    payload: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role(Role.admin)),
) -> User:
    """Change a user's role (admin only)."""
    user = await user_crud.get(db, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="USER_NOT_FOUND")
    # Guard: an admin can't demote themselves — avoids locking the last admin out.
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="CANNOT_CHANGE_OWN_ROLE")
    return await user_crud.set_role(db, user, payload.role)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role(Role.admin)),
) -> None:
    """Deactivate (soft-delete) a user — sets is_active=False (admin only)."""
    user = await user_crud.get(db, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="USER_NOT_FOUND")
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="CANNOT_DEACTIVATE_SELF")
    await user_crud.deactivate(db, user)
    return None
