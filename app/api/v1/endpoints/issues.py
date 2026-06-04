"""Issue endpoints.

Access is two-layered here:
  - ROLE tier (via require_role): who can list all / assign / delete.
  - ROW-level ownership (via _ensure_can_access): a member may only touch their
    OWN issue; staff+ may touch any. Role alone can't express "your own row".

Status changes (/status, /resolve) are deferred to the IssueService and wired in
the next file — they need the transition state machine, not plain CRUD.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import ensure_can_access_issue
from app.crud import equipment as equipment_crud
from app.crud import issue as issue_crud
from app.crud import user as user_crud
from app.db.session import get_db
from app.dependencies import get_current_user, require_role
from app.models.equipment import EquipmentStatus
from app.models.issue import Issue, IssueSeverity, IssueStatus
from app.models.user import Role, User
from app.schemas.issue import (
    IssueAssign,
    IssueCreate,
    IssueResponse,
    IssueStatusUpdate,
    IssueUpdate,
)
from app.services.issue_service import IssueService

router = APIRouter()


@router.get("/", response_model=list[IssueResponse])
async def list_issues(
    status_filter: IssueStatus | None = Query(None, alias="status"),
    severity: IssueSeverity | None = Query(None),
    equipment_id: UUID | None = Query(None),
    assigned_to: UUID | None = Query(None),
    reported_by: UUID | None = Query(None),
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _staff: User = Depends(require_role(Role.staff, Role.manager, Role.admin)),
) -> list[Issue]:
    """List all issues with optional filters (staff+ only)."""
    return await issue_crud.get_multi(
        db,
        skip=skip,
        limit=limit,
        status=status_filter,
        severity=severity,
        equipment_id=equipment_id,
        assigned_to_id=assigned_to,
        reported_by_id=reported_by,
        created_after=created_after,
        created_before=created_before,
    )


@router.post("/", response_model=IssueResponse, status_code=status.HTTP_201_CREATED)
async def create_issue(
    payload: IssueCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Issue:
    """Log a new issue against a piece of equipment (any authenticated user)."""
    equipment = await equipment_crud.get(db, payload.equipment_id)
    if equipment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="EQUIPMENT_NOT_FOUND")
    if equipment.status == EquipmentStatus.decommissioned:
        # Spec: you can't log issues against decommissioned equipment.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="EQUIPMENT_DECOMMISSIONED")
    issue = await issue_crud.create(db, payload, reported_by_id=current_user.id)
    # A brand-new critical issue must flip the equipment to under_maintenance.
    if issue.severity == IssueSeverity.critical:
        service = IssueService(db)
        await service.sync_equipment_status(issue.equipment_id)
        await db.commit()
    return issue


@router.get("/mine", response_model=list[IssueResponse])
async def list_my_issues(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Issue]:
    """List the caller's own reported issues."""
    return await issue_crud.get_multi(
        db, skip=skip, limit=limit, reported_by_id=current_user.id
    )


@router.get("/{issue_id}", response_model=IssueResponse)
async def get_issue(
    issue_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Issue:
    """Get one issue. Reporter can view their own; staff+ can view any."""
    issue = await issue_crud.get(db, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="ISSUE_NOT_FOUND")
    ensure_can_access_issue(current_user, issue)
    return issue


@router.patch("/{issue_id}", response_model=IssueResponse)
async def update_issue(
    issue_id: UUID,
    payload: IssueUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Issue:
    """Edit an issue's descriptive fields. Reporter or staff+ only."""
    issue = await issue_crud.get(db, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="ISSUE_NOT_FOUND")
    ensure_can_access_issue(current_user, issue)
    return await issue_crud.update(db, issue, payload)


@router.patch("/{issue_id}/assign", response_model=IssueResponse)
async def assign_issue(
    issue_id: UUID,
    payload: IssueAssign,
    db: AsyncSession = Depends(get_db),
    _staff: User = Depends(require_role(Role.staff, Role.manager, Role.admin)),
) -> Issue:
    """Assign an issue to a staff member (staff+)."""
    issue = await issue_crud.get(db, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="ISSUE_NOT_FOUND")
    assignee = await user_crud.get(db, payload.assigned_to_id)
    if assignee is None or not assignee.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="ASSIGNEE_NOT_FOUND")
    if assignee.role == Role.member:
        # Issues are worked by staff+, never assigned to a plain member.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="CANNOT_ASSIGN_TO_MEMBER")
    return await issue_crud.assign(db, issue, payload.assigned_to_id)


@router.delete("/{issue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_issue(
    issue_id: UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role(Role.admin)),
) -> None:
    """Hard-delete an issue (admin only). Comments cascade."""
    issue = await issue_crud.get(db, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="ISSUE_NOT_FOUND")
    await issue_crud.delete(db, issue)
    return None


@router.patch("/{issue_id}/status", response_model=IssueResponse)
async def change_issue_status(
    issue_id: UUID,
    payload: IssueStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Issue:
    """Transition an issue's status. The service enforces which transitions are
    legal and which roles may perform each — a member's request 403s there."""
    issue = await issue_crud.get(db, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="ISSUE_NOT_FOUND")
    service = IssueService(db)
    return await service.transition_status(
        issue, payload.status, current_user, note=payload.note
    )


@router.patch("/{issue_id}/resolve", response_model=IssueResponse)
async def resolve_issue(
    issue_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Issue:
    """Mark an issue resolved. A convenience alias for a transition to `resolved`;
    the service's role rule (manager+) and validity check still apply."""
    issue = await issue_crud.get(db, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="ISSUE_NOT_FOUND")
    service = IssueService(db)
    return await service.transition_status(issue, IssueStatus.resolved, current_user)
