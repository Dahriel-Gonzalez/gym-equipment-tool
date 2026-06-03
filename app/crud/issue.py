"""CRUD (data-access) layer for Issue.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.issue import Issue, IssueSeverity, IssueStatus
from app.schemas.issue import IssueCreate, IssueUpdate

# Relationships to pull in for any issue that becomes an IssueResponse.
# selectinload = one extra SELECT ... WHERE id IN (...) per relation; no row
# multiplication, so no .unique() needed (a joinedload on a collection would).
_LOAD_RELATIONS = (
    selectinload(Issue.equipment),
    selectinload(Issue.reported_by),
    selectinload(Issue.assigned_to),
    selectinload(Issue.resolved_by),
)


async def get(db: AsyncSession, issue_id: UUID) -> Issue | None:
    """Fetch one issue (with relations loaded), or None."""
    stmt = select(Issue).where(Issue.id == issue_id).options(*_LOAD_RELATIONS)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_multi(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 20,
    status: IssueStatus | None = None,
    severity: IssueSeverity | None = None,
    equipment_id: UUID | None = None,
    assigned_to_id: UUID | None = None,
    reported_by_id: UUID | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> list[Issue]:
    """List issues, applying only the filters provided. Newest first.

    `reported_by_id` doubles as the "my issues" filter — GET /issues/mine just
    calls this with reported_by_id=current_user.id, no separate query needed.
    """
    stmt = select(Issue)
    if status is not None:
        stmt = stmt.where(Issue.status == status)
    if severity is not None:
        stmt = stmt.where(Issue.severity == severity)
    if equipment_id is not None:
        stmt = stmt.where(Issue.equipment_id == equipment_id)
    if assigned_to_id is not None:
        stmt = stmt.where(Issue.assigned_to_id == assigned_to_id)
    if reported_by_id is not None:
        stmt = stmt.where(Issue.reported_by_id == reported_by_id)
    if created_after is not None:
        stmt = stmt.where(Issue.created_at >= created_after)
    if created_before is not None:
        stmt = stmt.where(Issue.created_at <= created_before)

    stmt = (
        stmt.options(*_LOAD_RELATIONS)
        .order_by(Issue.created_at.desc(), Issue.id)  # id tiebreaker = stable paging
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create(db: AsyncSession, issue_in: IssueCreate, reported_by_id: UUID) -> Issue:
    """Insert a new issue. `reported_by_id` comes from the authenticated user,
    never from the request body."""
    issue = Issue(
        equipment_id=issue_in.equipment_id,
        title=issue_in.title,
        description=issue_in.description,
        severity=issue_in.severity,
        reported_by_id=reported_by_id,
        # status defaults to open at the model level.
    )
    db.add(issue)
    try:
        await db.commit()
    except IntegrityError as exc:
        # e.g. equipment_id points at a non-existent asset (FK violation).
        await db.rollback()
        raise ValueError("Invalid equipment reference") from exc
    # Re-fetch with relations: the just-built object has FK ids but its
    # relationship attributes (issue.equipment, .reported_by) are unloaded.
    return await get(db, issue.id)


async def update(db: AsyncSession, issue: Issue, issue_in: IssueUpdate) -> Issue:
    """Partial update of an already-loaded issue's descriptive fields.

    Assumes `issue` was loaded via get() (relations present). Because the session
    uses expire_on_commit=False, those relations stay loaded after commit, so the
    same instance is safe to return and serialize.
    """
    data = issue_in.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(issue, field, value)
    await db.commit()
    return issue


async def assign(db: AsyncSession, issue: Issue, assigned_to_id: UUID | None) -> Issue:
    """Set (or clear) the assignee. Re-fetches so the new assigned_to relation
    is loaded for the response."""
    issue.assigned_to_id = assigned_to_id
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError("Invalid assignee") from exc
    return await get(db, issue.id)


async def delete(db: AsyncSession, issue: Issue) -> None:
    """Hard-delete an issue (admin action). Its comments are removed by the
    issue_id FK's ON DELETE CASCADE."""
    await db.delete(issue)
    await db.commit()
