"""CRUD (data-access) layer for Equipment.

Raw queries only. The list helper builds its WHERE clause conditionally from the
optional filters the endpoint passes through.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment import Equipment, EquipmentStatus
from app.schemas.equipment import EquipmentCreate, EquipmentUpdate


async def get(db: AsyncSession, equipment_id: UUID) -> Equipment | None:
    """Fetch one non-deleted equipment row by id, or None."""
    stmt = select(Equipment).where(
        Equipment.id == equipment_id,
        Equipment.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_multi(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 20,
    status: EquipmentStatus | None = None,
    category: str | None = None,
    location: str | None = None,
    search: str | None = None,
) -> tuple[list[Equipment], int]:
    """List equipment + total count, applying only the filters provided.

    Build the filtered base once; COUNT over it for `total`, then add ordering +
    paging for the page. Each filter is an optional AND clause; unset filters
    simply don't narrow the query. `search` is a case-insensitive match on name.
    """
    # Soft-deleted rows are excluded from every list.
    base = select(Equipment).where(Equipment.deleted_at.is_(None))
    if status is not None:
        base = base.where(Equipment.status == status)
    if category is not None:
        base = base.where(Equipment.category == category)
    if location is not None:
        base = base.where(Equipment.location == location)
    if search:
        # ILIKE = case-insensitive LIKE; %term% = contains. The value is bound as
        # a parameter (not string-formatted into SQL), so this isn't injectable.
        base = base.where(Equipment.name.ilike(f"%{search}%"))

    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = await db.execute(
        base.order_by(Equipment.created_at, Equipment.id).offset(skip).limit(limit)
    )
    return list(rows.scalars().all()), total


async def create(db: AsyncSession, equipment_in: EquipmentCreate) -> Equipment:
    """Insert a new equipment row. Raises ValueError on a duplicate serial_number."""
    equipment = Equipment(**equipment_in.model_dump())
    db.add(equipment)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError("Serial number already exists") from exc
    await db.refresh(equipment)
    return equipment


async def update(
    db: AsyncSession, equipment: Equipment, equipment_in: EquipmentUpdate
) -> Equipment:
    """Apply a partial update to an already-loaded equipment row."""
    data = equipment_in.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(equipment, field, value)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError("Serial number already exists") from exc
    await db.refresh(equipment)
    return equipment


async def delete(db: AsyncSession, equipment: Equipment) -> None:
    """Soft-delete: stamp deleted_at. The row stays (its issues/history remain
    intact and its FK references stay valid); reads filter it out via
    deleted_at IS NULL, so a deleted asset 404s on the next fetch."""
    equipment.deleted_at = datetime.now(timezone.utc)
    await db.commit()
