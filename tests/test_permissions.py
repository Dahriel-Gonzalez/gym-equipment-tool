"""The permission matrix: endpoint x role -> expected access outcome.

Two kinds of access control are exercised:
  - ROLE-TIER (require_role): parametrized below — disallowed roles get 403,
    allowed roles pass the gate (whatever they get, it's not 401/403).
  - ROW-LEVEL ownership: the issue-visibility tests at the bottom.

For "allowed" we assert the status is NOT 401/403 (it may be 200/201/404) — the
point is the permission gate let them through, not what happened after.
"""
from __future__ import annotations

import uuid

import pytest

from app.core.security import hash_password
from app.models.user import Role, User

ALL = {Role.member, Role.staff, Role.manager, Role.admin}
STAFF_UP = {Role.staff, Role.manager, Role.admin}
MANAGER_UP = {Role.manager, Role.admin}
ADMIN = {Role.admin}

_RID = str(uuid.uuid4())  # a random, non-existent id (forces 404, never 403/401)

# (method, url, json body, set of roles allowed through the gate)
CASES = [
    ("get", "/api/v1/equipment/", None, ALL),
    ("get", "/api/v1/issues/", None, STAFF_UP),
    ("get", "/api/v1/users/", None, ADMIN),
    ("get", f"/api/v1/users/{_RID}", None, MANAGER_UP),
    ("patch", f"/api/v1/users/{_RID}/role", {"role": "staff"}, ADMIN),
    ("delete", f"/api/v1/users/{_RID}", None, ADMIN),
    ("post", "/api/v1/equipment/", {"name": "T", "category": "Cardio", "location": "A"}, MANAGER_UP),
    ("delete", f"/api/v1/equipment/{_RID}", None, ADMIN),
    ("patch", f"/api/v1/issues/{_RID}/assign", {"assigned_to_id": _RID}, STAFF_UP),
    ("delete", f"/api/v1/issues/{_RID}", None, ADMIN),
]


@pytest.mark.parametrize("method,url,body,allowed", CASES)
async def test_requires_authentication(client, method, url, body, allowed):
    """No token at all -> 401 on every protected endpoint."""
    resp = await client.request(method, url, json=body)
    assert resp.status_code == 401


@pytest.mark.parametrize("method,url,body,allowed", CASES)
async def test_disallowed_roles_get_403(client, users, auth_header, method, url, body, allowed):
    for role in ALL - allowed:
        resp = await client.request(method, url, json=body, headers=auth_header(users[role]))
        assert resp.status_code == 403, f"{role.value} should be forbidden: {method.upper()} {url}"


@pytest.mark.parametrize("method,url,body,allowed", CASES)
async def test_allowed_roles_pass_gate(client, users, auth_header, method, url, body, allowed):
    for role in allowed:
        resp = await client.request(method, url, json=body, headers=auth_header(users[role]))
        assert resp.status_code not in (401, 403), (
            f"{role.value} should pass: {method.upper()} {url} got {resp.status_code}"
        )


# --- Row-level ownership (role tier alone can't express "your own issue") ---

async def test_issue_visibility_by_ownership(client, users, auth_header, db_session):
    # Manager registers equipment; a member logs an issue against it.
    eq = await client.post(
        "/api/v1/equipment/",
        json={"name": "Bike #1", "category": "Cardio", "location": "Zone A"},
        headers=auth_header(users[Role.manager]),
    )
    equipment_id = eq.json()["id"]
    logged = await client.post(
        "/api/v1/issues/",
        json={
            "equipment_id": equipment_id,
            "title": "Broken pedal",
            "description": "The left pedal is loose and wobbles.",
        },
        headers=auth_header(users[Role.member]),
    )
    assert logged.status_code == 201
    issue_id = logged.json()["id"]

    # The reporter can view their own issue.
    own = await client.get(f"/api/v1/issues/{issue_id}", headers=auth_header(users[Role.member]))
    assert own.status_code == 200

    # A DIFFERENT member cannot — 403, not because of role but because of ownership.
    other = User(
        email="member2@test.com",
        full_name="Member Two",
        hashed_password=hash_password("password123"),
        role=Role.member,
        is_active=True,
    )
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    blocked = await client.get(f"/api/v1/issues/{issue_id}", headers=auth_header(other))
    assert blocked.status_code == 403

    # Staff can view ANY issue.
    staff = await client.get(f"/api/v1/issues/{issue_id}", headers=auth_header(users[Role.staff]))
    assert staff.status_code == 200


async def test_member_cannot_change_roles(client, users, auth_header):
    """A self-promotion attempt via the admin-only role endpoint is 403, not 200."""
    target = users[Role.staff]
    resp = await client.patch(
        f"/api/v1/users/{target.id}/role",
        json={"role": "admin"},
        headers=auth_header(users[Role.member]),
    )
    assert resp.status_code == 403
