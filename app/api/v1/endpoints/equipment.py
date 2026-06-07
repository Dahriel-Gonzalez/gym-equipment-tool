"""Equipment endpoints.

Access tiers (per spec):
  - GET list / GET detail : any authenticated user
  - POST / PATCH          : manager+ (require_role(manager, admin))
  - DELETE                : admin only (soft delete)
"""
from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.crud import equipment as equipment_crud
from app.crud import issue as issue_crud
from app.db.session import get_db
from app.dependencies import get_current_user, require_role
from app.models.equipment import Equipment, EquipmentStatus
from app.models.issue import Issue
from app.models.user import Role, User
from app.schemas.equipment import EquipmentCreate, EquipmentResponse, EquipmentUpdate
from app.schemas.issue import IssueResponse
from app.schemas.pagination import PaginatedResponse, PaginationParams

router = APIRouter()

# All cached equipment-list pages live under this key prefix, so any write can
# invalidate the whole family with cache.delete_prefix(_LIST_CACHE_PREFIX).
_LIST_CACHE_PREFIX = "equipment:list:"
# Short TTL: the invalidation-on-write below keeps the cache correct; this is just
# the backstop that bounds staleness if an invalidation is ever missed.
_LIST_CACHE_TTL_SECONDS = 60


def _list_cache_key(
    *,
    skip: int,
    limit: int,
    status: EquipmentStatus | None,
    category: str | None,
    location: str | None,
    search: str | None,
) -> str:
    """Build a deterministic cache key from the exact filter + pagination inputs.

    Two requests cache-hit each other only if every parameter matches, so each
    distinct page/filter combination gets its own entry. sort_keys makes the
    serialization canonical (key order can't produce two keys for one query).
    """
    params = {
        "skip": skip,
        "limit": limit,
        "status": status.value if status is not None else None,
        "category": category,
        "location": location,
        "search": search,
    }
    return _LIST_CACHE_PREFIX + json.dumps(params, sort_keys=True, separators=(",", ":"))


@router.get("/", response_model=PaginatedResponse[EquipmentResponse])
async def list_equipment(
    # alias="status" keeps the query key `?status=` while avoiding shadowing the
    # imported fastapi `status` module inside this function.
    status_filter: EquipmentStatus | None = Query(None, alias="status"),
    category: str | None = Query(None),
    location: str | None = Query(None),
    search: str | None = Query(None),
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> PaginatedResponse[EquipmentResponse]:
    """List equipment with optional filters (status/category/location/search).

    Cache-aside: check Redis first; on a miss, query Postgres and store the
    serialized page. Safe to cache because this list is identical for every
    authenticated user (no per-user fields), so one entry serves everyone.
    """
    cache_key = _list_cache_key(
        skip=pagination.skip,
        limit=pagination.limit,
        status=status_filter,
        category=category,
        location=location,
        search=search,
    )
    cached = await cache.get_json(cache_key)
    if cached is not None:
        # Re-validate the stored dict back into the model: keeps the return type
        # honest and rejects a stale entry whose shape predates a schema change.
        return PaginatedResponse[EquipmentResponse].model_validate(cached)

    items, total = await equipment_crud.get_multi(
        db,
        skip=pagination.skip,
        limit=pagination.limit,
        status=status_filter,
        category=category,
        location=location,
        search=search,
    )
    response = PaginatedResponse[EquipmentResponse].create(
        items, total, skip=pagination.skip, limit=pagination.limit
    )
    # mode="json" yields JSON-safe primitives (UUID/datetime -> str) so the value
    # round-trips cleanly through json.dumps in the cache layer.
    await cache.set_json(
        cache_key, response.model_dump(mode="json"), ttl_seconds=_LIST_CACHE_TTL_SECONDS
    )
    return response


@router.post("/", response_model=EquipmentResponse, status_code=status.HTTP_201_CREATED)
async def create_equipment(
    payload: EquipmentCreate,
    db: AsyncSession = Depends(get_db),
    _mgr: User = Depends(require_role(Role.manager, Role.admin)),
) -> Equipment:
    """Add a new equipment asset (manager+)."""
    try:
        equipment = await equipment_crud.create(db, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="SERIAL_NUMBER_EXISTS") from exc
    # A new asset can appear in (or shift) any list page — drop all cached pages.
    await cache.delete_prefix(_LIST_CACHE_PREFIX)
    return equipment


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
        updated = await equipment_crud.update(db, equipment, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="SERIAL_NUMBER_EXISTS") from exc
    # Edited fields (status/category/name…) change list contents and filtering.
    await cache.delete_prefix(_LIST_CACHE_PREFIX)
    return updated


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
    # A soft-deleted asset must drop out of every cached page.
    await cache.delete_prefix(_LIST_CACHE_PREFIX)
    return None


@router.get("/{equipment_id}/issues", response_model=PaginatedResponse[IssueResponse])
async def list_equipment_issues(
    equipment_id: UUID,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> PaginatedResponse[IssueResponse]:
    """List issues logged against one piece of equipment.

    NOTE: spec marks this 'Any' authenticated user, but GET /issues/ is staff+.
    So a member can see ALL issues for an asset here while being blocked from the
    general list — a visibility inconsistency. Following the spec as written;
    tighten to require_role(staff+) if that leak matters.
    """
    if await equipment_crud.get(db, equipment_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="EQUIPMENT_NOT_FOUND")
    items, total = await issue_crud.get_multi(
        db, skip=pagination.skip, limit=pagination.limit, equipment_id=equipment_id
    )
    return PaginatedResponse.create(
        items, total, skip=pagination.skip, limit=pagination.limit
    )
