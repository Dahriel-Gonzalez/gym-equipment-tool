"""Issue business logic: the status state machine and its side effects.

This is the ONLY place an issue's status changes. Endpoints call
IssueService.transition_status; CRUD never sets status. Centralizing it here
means the legal-transition rules, per-transition role checks, resolution
stamping, and the equipment auto-maintenance side effect can't be bypassed.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status as http_status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import equipment as equipment_crud
from app.crud import issue as issue_crud
from app.models.comment import Comment
from app.models.equipment import EquipmentStatus
from app.models.issue import Issue, IssueSeverity, IssueStatus
from app.models.user import Role, User

# Single source of truth for the state machine:
#   (from_status, to_status) -> the set of roles allowed to make that move.
# Presence in this table = the transition is allowed; the value = WHO may do it.
TRANSITIONS: dict[tuple[IssueStatus, IssueStatus], set[Role]] = {
    (IssueStatus.open, IssueStatus.in_progress): {Role.staff, Role.manager, Role.admin},
    (IssueStatus.open, IssueStatus.resolved): {Role.manager, Role.admin},
    (IssueStatus.in_progress, IssueStatus.open): {Role.staff, Role.manager, Role.admin},
    (IssueStatus.in_progress, IssueStatus.resolved): {Role.manager, Role.admin},
    (IssueStatus.resolved, IssueStatus.open): {Role.manager, Role.admin},
    (IssueStatus.resolved, IssueStatus.closed): {Role.manager, Role.admin},
    # closed is terminal: no outgoing transitions.
}

# Issue states that still count as "live" for the equipment-maintenance rule.
_ACTIVE_STATUSES = (IssueStatus.open, IssueStatus.in_progress)


class IssueService:
    """Constructed per request with the active session: `IssueService(db)`."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def transition_status(
        self,
        issue: Issue,
        new_status: IssueStatus,
        actor: User,
        note: str | None = None,
    ) -> Issue:
        """Move `issue` to `new_status` if the transition is legal and the actor
        is allowed to make it; stamp resolution fields; sync equipment status.

        Raises 422 INVALID_TRANSITION for an illegal move, 403 for a legal move
        the actor's role can't perform.
        """
        key = (issue.status, new_status)

        if key not in TRANSITIONS:
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="INVALID_TRANSITION"
            )
        
        if actor.role not in TRANSITIONS[key]:
            raise HTTPException(
                http_status.HTTP_403_FORBIDDEN, detail="INSUFFICIENT_PERMISSIONS"
            )

        issue.status = new_status
        if new_status == IssueStatus.resolved:
            issue.resolved_at = datetime.now(timezone.utc)
            issue.resolved_by_id = actor.id
        elif new_status == IssueStatus.open:
            # Reopened — clear the prior resolution stamps.
            issue.resolved_at = None
            issue.resolved_by_id = None

        await self.sync_equipment_status(issue.equipment_id)

        # If a note was supplied, record it as an internal comment in the SAME
        # unit of work — added to the session here, persisted by the commit below.
        # Internal so it reads as a staff-facing audit note, not shown to members.
        if note:
            self.db.add(
                Comment(
                    issue_id=issue.id,
                    author_id=actor.id,
                    body=note,
                    is_internal=True,
                )
            )

        await self.db.commit()
        return await issue_crud.get(self.db, issue.id)

    async def sync_equipment_status(self, equipment_id) -> None:
        """Flip equipment to under_maintenance while it has an active critical
        issue, and back to operational once it doesn't. Decommissioned equipment
        is left alone (a terminal, manually-set state).

        Also the hook for issue CREATION: the create endpoint should call this
        after logging a critical issue so a new asset flips to maintenance too.
        """
        equipment = await equipment_crud.get(self.db, equipment_id)
        if equipment is None or equipment.status == EquipmentStatus.decommissioned:
            return

        if await self._has_active_critical(equipment_id):
            equipment.status = EquipmentStatus.under_maintenance
        elif equipment.status == EquipmentStatus.under_maintenance:
            # No active critical issues left — release it back to operational.
            equipment.status = EquipmentStatus.operational

    async def _has_active_critical(self, equipment_id) -> bool:
        """True if the equipment has a critical-severity issue still open or in
        progress. Autoflush means the in-flight status change above is already
        visible to this SELECT, so the count reflects the transition we just made.
        """
        stmt = (
            select(func.count())
            .select_from(Issue)
            .where(
                Issue.equipment_id == equipment_id,
                Issue.severity == IssueSeverity.critical,
                Issue.status.in_(_ACTIVE_STATUSES),
            )
        )
        result = await self.db.execute(stmt)
        return (result.scalar_one() or 0) > 0
