"""Authorization predicates that go beyond simple role tiers.

require_role (in dependencies.py) handles "what kind of user are you?". These
helpers handle row-level questions like "is this your issue?" that depend on the
specific object, so they live here and are shared by the issue + comment routers.
"""
from __future__ import annotations

from fastapi import HTTPException, status

from app.models.issue import Issue
from app.models.user import Role, User

STAFF_AND_UP = frozenset({Role.staff, Role.manager, Role.admin})
MANAGER_AND_UP = frozenset({Role.manager, Role.admin})


def is_staff_or_above(user: User) -> bool:
    return user.role in STAFF_AND_UP


def is_manager_or_above(user: User) -> bool:
    return user.role in MANAGER_AND_UP


def can_access_issue(user: User, issue: Issue) -> bool:
    """Staff+ may access any issue; a member only their own (as reporter)."""
    return is_staff_or_above(user) or issue.reported_by_id == user.id


def ensure_can_access_issue(user: User, issue: Issue) -> None:
    """Raise 403 unless the user may access this issue."""
    if not can_access_issue(user, issue):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="FORBIDDEN")
