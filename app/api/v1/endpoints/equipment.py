"""Equipment endpoints.

Access tiers (per spec):
  - GET list / GET detail : any authenticated user
  - POST / PATCH          : manager+ (require_role(manager, admin))
  - DELETE                : admin only (soft delete)
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import equipment as equipment_crud
from app.db.session import get_db
from app.dependencies import get_current_user, require_role
from app.models.equipment import Equipment, EquipmentStatus
from app.models.user import Role, User
from app.schemas.equipment import EquipmentCreate, EquipmentResponse, EquipmentUpdate

router = APIRouter()


@router.get("/", response_model=list[EquipmentResponse])
async def list_equipment(
    # alias="status" keeps the query key `?status=` while avoiding shadowing the
    # imported fastapi `status` module inside this function.
    status_filter: EquipmentStatus | None = Query(None, alias="status"),
    category: str | None = Query(None),
    location: str | None = Query(None),
    search: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[Equipment]:
    """List equipment with optional filters (status/category/location/search)."""
    return await equipment_crud.get_multi(
        db,
        skip=skip,
        limit=limit,
        status=status_filter,
        category=category,
        location=location,
        search=search,
    )


@router.post("/", response_model=EquipmentResponse, status_code=status.HTTP_201_CREATED)
async def create_equipment(
    payload: EquipmentCreate,
    db: AsyncSession = Depends(get_db),
    _mgr: User = Depends(require_role(Role.manager, Role.admin)),
) -> Equipment:
    """Add a new equipment asset (manager+)."""
    try:
        return await equipment_crud.create(db, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="SERIAL_NUMBER_EXISTS") from exc


@router.get("/{equipment_id}", response_model=EquipmentResponse)
async def get_equipment(
    equipment_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Equipment:
    """Fetch one equipment record (any authenticated user)."""
    equipment = await equipment_crud.get(db, equipment_id)
    if equipment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="EQUIPMENT_NOT_FOUND")
    return equipment


@router.patch("/{equipment_id}", response_model=EquipmentResponse)
async def update_equipment(
    equipment_id: UUID,
    payload: EquipmentUpdate,
    db: AsyncSession = Depends(get_db),
    _mgr: User = Depends(require_role(Role.manager, Role.admin)),
) -> Equipment:
    """Update equipment fields (manager+)."""
    equipment = await equipment_crud.get(db, equipment_id)
    if equipment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="EQUIPMENT_NOT_FOUND")
    try:
        return await equipment_crud.update(db, equipment, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="SERIAL_NUMBER_EXISTS") from exc


@router.delete("/{equipment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_equipment(
    equipment_id: UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role(Role.admin)),
) -> None:
    """Soft-delete equipment (admin only)."""
    equipment = await equipment_crud.get(db, equipment_id)
    if equipment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="EQUIPMENT_NOT_FOUND")
    await equipment_crud.delete(db, equipment)
    return None


# DEFERRED: GET /{equipment_id}/issues — list issues for a piece of equipment.
# Needs the Issue layer (issue crud + IssueResponse schema), which is a later
# feature. Wire it when those exist:
#
# @router.get("/{equipment_id}/issues", response_model=list[IssueResponse])
# async def list_equipment_issues(
#     equipment_id: UUID,
#     db: AsyncSession = Depends(get_db),
#     _user: User = Depends(get_current_user),
# ) -> list[Issue]:
#     if await equipment_crud.get(db, equipment_id) is None:
#         raise HTTPException(status.HTTP_404_NOT_FOUND, detail="EQUIPMENT_NOT_FOUND")
#     return await issue_crud.get_multi(db, equipment_id=equipment_id)
