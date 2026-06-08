"""Issue domain tests: creation rules, the status state machine, the
critical-issue -> equipment maintenance automation, assignment, and deletion.

Helpers create the equipment + issue prerequisites via the API so each test
exercises the real stack end to end.
"""
from __future__ import annotations

import uuid

from app.models.user import Role

EQUIPMENT_URL = "/api/v1/equipment/"
ISSUES_URL = "/api/v1/issues/"


async def _create_equipment(client, auth_header, users, **overrides) -> str:
    body = {"name": "Treadmill #1", "category": "Cardio", "location": "Zone A"}
    body.update(overrides)
    resp = await client.post(EQUIPMENT_URL, json=body, headers=auth_header(users[Role.manager]))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_issue(client, auth_header, users, equipment_id, *, severity="medium", reporter=Role.member):
    resp = await client.post(
        ISSUES_URL,
        json={
            "equipment_id": equipment_id,
            "title": "Loose bolt found",
            "description": "A bolt on the frame is loose and rattles.",
            "severity": severity,
        },
        headers=auth_header(users[reporter]),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _equipment_status(client, auth_header, users, equipment_id) -> str:
    resp = await client.get(f"{EQUIPMENT_URL}{equipment_id}", headers=auth_header(users[Role.staff]))
    assert resp.status_code == 200
    return resp.json()["status"]


# --- Creation ---

async def test_create_issue_defaults(client, users, auth_header):
    eq = await _create_equipment(client, auth_header, users)
    issue = await _create_issue(client, auth_header, users, eq)
    assert issue["status"] == "open"                       # always starts open
    assert issue["reported_by"]["id"] == str(users[Role.member].id)  # reporter = caller
    assert issue["equipment"]["id"] == eq                  # nested summary
    assert issue["assigned_to"] is None


async def test_create_issue_unknown_equipment_404(client, users, auth_header):
    resp = await client.post(
        ISSUES_URL,
        json={
            "equipment_id": str(uuid.uuid4()),
            "title": "Title here",
            "description": "Ten chars plus.",
        },
        headers=auth_header(users[Role.member]),
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "EQUIPMENT_NOT_FOUND"


async def test_cannot_log_issue_on_decommissioned(client, users, auth_header):
    eq = await _create_equipment(client, auth_header, users)
    await client.patch(
        f"{EQUIPMENT_URL}{eq}",
        json={"status": "decommissioned"},
        headers=auth_header(users[Role.manager]),
    )
    resp = await client.post(
        ISSUES_URL,
        json={"equipment_id": eq, "title": "A title", "description": "Long enough text."},
        headers=auth_header(users[Role.member]),
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "EQUIPMENT_DECOMMISSIONED"


# --- Listing ---

async def test_list_is_staff_only_but_mine_is_open(client, users, auth_header):
    eq = await _create_equipment(client, auth_header, users)
    await _create_issue(client, auth_header, users, eq)

    forbidden = await client.get(ISSUES_URL, headers=auth_header(users[Role.member]))
    assert forbidden.status_code == 403

    listed = await client.get(ISSUES_URL, headers=auth_header(users[Role.staff]))
    assert listed.status_code == 200
    assert listed.json()["total"] == 1                     # pagination envelope

    mine = await client.get(f"{ISSUES_URL}mine", headers=auth_header(users[Role.member]))
    assert mine.status_code == 200
    assert mine.json()["total"] == 1


# --- State machine ---

async def test_valid_transition_open_to_in_progress(client, users, auth_header):
    eq = await _create_equipment(client, auth_header, users)
    issue = await _create_issue(client, auth_header, users, eq)
    resp = await client.patch(
        f"{ISSUES_URL}{issue['id']}/status",
        json={"status": "in_progress"},
        headers=auth_header(users[Role.staff]),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"


async def test_illegal_transition_open_to_closed_422(client, users, auth_header):
    eq = await _create_equipment(client, auth_header, users)
    issue = await _create_issue(client, auth_header, users, eq)
    resp = await client.patch(
        f"{ISSUES_URL}{issue['id']}/status",
        json={"status": "closed"},                         # open -> closed is illegal
        headers=auth_header(users[Role.manager]),
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "INVALID_TRANSITION"


async def test_transition_role_enforced(client, users, auth_header):
    eq = await _create_equipment(client, auth_header, users)
    issue = await _create_issue(client, auth_header, users, eq)
    # open -> resolved requires manager+, so staff is rejected...
    staff_try = await client.patch(
        f"{ISSUES_URL}{issue['id']}/status",
        json={"status": "resolved"},
        headers=auth_header(users[Role.staff]),
    )
    assert staff_try.status_code == 403
    assert staff_try.json()["error"] == "INSUFFICIENT_PERMISSIONS"
    # ...but a manager can, and it stamps resolution fields.
    mgr = await client.patch(
        f"{ISSUES_URL}{issue['id']}/status",
        json={"status": "resolved"},
        headers=auth_header(users[Role.manager]),
    )
    assert mgr.status_code == 200
    body = mgr.json()
    assert body["status"] == "resolved"
    assert body["resolved_at"] is not None
    assert body["resolved_by"]["id"] == str(users[Role.manager].id)


async def test_reopen_clears_resolution(client, users, auth_header):
    eq = await _create_equipment(client, auth_header, users)
    issue = await _create_issue(client, auth_header, users, eq)
    await client.patch(
        f"{ISSUES_URL}{issue['id']}/resolve", headers=auth_header(users[Role.manager])
    )
    reopened = await client.patch(
        f"{ISSUES_URL}{issue['id']}/status",
        json={"status": "open"},                           # resolved -> open (manager+)
        headers=auth_header(users[Role.manager]),
    )
    assert reopened.status_code == 200
    body = reopened.json()
    assert body["status"] == "open"
    assert body["resolved_at"] is None                     # stamps cleared on reopen
    assert body["resolved_by"] is None


# --- Critical-issue -> equipment maintenance automation ---

async def test_critical_issue_flips_equipment_to_maintenance(client, users, auth_header):
    eq = await _create_equipment(client, auth_header, users)
    assert await _equipment_status(client, auth_header, users, eq) == "operational"
    await _create_issue(client, auth_header, users, eq, severity="critical")
    assert await _equipment_status(client, auth_header, users, eq) == "under_maintenance"


async def test_resolving_critical_returns_to_operational(client, users, auth_header):
    eq = await _create_equipment(client, auth_header, users)
    issue = await _create_issue(client, auth_header, users, eq, severity="critical")
    assert await _equipment_status(client, auth_header, users, eq) == "under_maintenance"
    await client.patch(
        f"{ISSUES_URL}{issue['id']}/resolve", headers=auth_header(users[Role.manager])
    )
    assert await _equipment_status(client, auth_header, users, eq) == "operational"


# --- Assignment ---

async def test_assign_to_staff_and_reject_member(client, users, auth_header):
    eq = await _create_equipment(client, auth_header, users)
    issue = await _create_issue(client, auth_header, users, eq)

    ok = await client.patch(
        f"{ISSUES_URL}{issue['id']}/assign",
        json={"assigned_to_id": str(users[Role.manager].id)},
        headers=auth_header(users[Role.staff]),
    )
    assert ok.status_code == 200
    assert ok.json()["assigned_to"]["id"] == str(users[Role.manager].id)

    to_member = await client.patch(
        f"{ISSUES_URL}{issue['id']}/assign",
        json={"assigned_to_id": str(users[Role.member].id)},
        headers=auth_header(users[Role.staff]),
    )
    assert to_member.status_code == 400
    assert to_member.json()["error"] == "CANNOT_ASSIGN_TO_MEMBER"

    unknown = await client.patch(
        f"{ISSUES_URL}{issue['id']}/assign",
        json={"assigned_to_id": str(uuid.uuid4())},
        headers=auth_header(users[Role.staff]),
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"] == "ASSIGNEE_NOT_FOUND"


# --- Deletion ---

async def test_delete_issue_admin_only(client, users, auth_header):
    eq = await _create_equipment(client, auth_header, users)
    issue = await _create_issue(client, auth_header, users, eq)
    issue_id = issue["id"]

    staff_try = await client.delete(
        f"{ISSUES_URL}{issue_id}", headers=auth_header(users[Role.staff])
    )
    assert staff_try.status_code == 403

    admin = await client.delete(
        f"{ISSUES_URL}{issue_id}", headers=auth_header(users[Role.admin])
    )
    assert admin.status_code == 204

    gone = await client.get(
        f"{ISSUES_URL}{issue_id}", headers=auth_header(users[Role.admin])
    )
    assert gone.status_code == 404


# --- CSV export ---

EXPORT_URL = "/api/v1/issues/export"


async def test_export_issues_csv_staff(client, users, auth_header):
    eq = await _create_equipment(client, auth_header, users)
    await _create_issue(client, auth_header, users, eq, severity="high")

    resp = await client.get(EXPORT_URL, headers=auth_header(users[Role.staff]))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]

    lines = [ln for ln in resp.text.splitlines() if ln.strip()]
    assert lines[0].startswith("id,title,equipment,severity,status,")  # header
    assert len(lines) == 2                                             # header + 1 issue
    assert "Treadmill #1" in resp.text          # equipment flattened to its name
    assert "member@test.com" in resp.text       # reporter flattened to email
    assert ",high," in resp.text                # severity enum value


async def test_export_issues_forbidden_for_member(client, users, auth_header):
    """Export is review-oriented: members (the default signup tier) can't pull it."""
    resp = await client.get(EXPORT_URL, headers=auth_header(users[Role.member]))
    assert resp.status_code == 403


async def test_export_issues_respects_filters(client, users, auth_header):
    eq = await _create_equipment(client, auth_header, users)
    await _create_issue(client, auth_header, users, eq, severity="low")
    await _create_issue(client, auth_header, users, eq, severity="critical")

    resp = await client.get(
        f"{EXPORT_URL}?severity=critical", headers=auth_header(users[Role.manager])
    )
    assert resp.status_code == 200
    lines = [ln for ln in resp.text.splitlines() if ln.strip()]
    assert len(lines) == 2          # header + only the critical issue
    assert ",critical," in resp.text
    assert ",low," not in resp.text
