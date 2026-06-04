"""Equipment tests: CRUD happy paths, the serial-number 409, filters, the
pagination envelope, and the soft-delete-hides-from-reads behavior.

Equipment writes are manager+/admin; reads are any authenticated user (we read
as staff). Each test starts from an empty DB (function-scoped engine).
"""
from __future__ import annotations

import uuid

from app.models.user import Role

EQUIPMENT_URL = "/api/v1/equipment/"


async def _create(client, auth_header, users, **fields) -> dict:
    body = {"name": "Item", "category": "Cardio", "location": "Zone A"}
    body.update(fields)
    resp = await client.post(EQUIPMENT_URL, json=body, headers=auth_header(users[Role.manager]))
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- Create / read ---

async def test_create_defaults(client, users, auth_header):
    eq = await _create(client, auth_header, users)
    assert eq["status"] == "operational"      # model default
    assert eq["serial_number"] is None
    assert "id" in eq


async def test_create_with_explicit_status(client, users, auth_header):
    eq = await _create(client, auth_header, users, status="under_maintenance")
    assert eq["status"] == "under_maintenance"


async def test_duplicate_serial_number_409(client, users, auth_header):
    await _create(client, auth_header, users, serial_number="SN-1")
    dup = await client.post(
        EQUIPMENT_URL,
        json={"name": "Other", "category": "Cardio", "location": "B", "serial_number": "SN-1"},
        headers=auth_header(users[Role.manager]),
    )
    assert dup.status_code == 409
    assert dup.json()["error"] == "SERIAL_NUMBER_EXISTS"


async def test_get_and_404(client, users, auth_header):
    eq = await _create(client, auth_header, users)
    found = await client.get(f"{EQUIPMENT_URL}{eq['id']}", headers=auth_header(users[Role.staff]))
    assert found.status_code == 200
    assert found.json()["id"] == eq["id"]

    missing = await client.get(f"{EQUIPMENT_URL}{uuid.uuid4()}", headers=auth_header(users[Role.staff]))
    assert missing.status_code == 404
    assert missing.json()["error"] == "EQUIPMENT_NOT_FOUND"


async def test_partial_update(client, users, auth_header):
    eq = await _create(client, auth_header, users, name="Rower")
    resp = await client.patch(
        f"{EQUIPMENT_URL}{eq['id']}",
        json={"location": "Zone B"},          # only location sent
        headers=auth_header(users[Role.manager]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["location"] == "Zone B"
    assert body["name"] == "Rower"            # untouched fields preserved


# --- Filtering ---

async def test_filters(client, users, auth_header):
    await _create(client, auth_header, users, name="Treadmill 1", category="Cardio")
    await _create(
        client, auth_header, users,
        name="Bench Press", category="Free Weights", status="under_maintenance",
    )
    staff = auth_header(users[Role.staff])

    by_status = await client.get(EQUIPMENT_URL, params={"status": "operational"}, headers=staff)
    assert by_status.json()["total"] == 1
    assert by_status.json()["items"][0]["name"] == "Treadmill 1"

    by_search = await client.get(EQUIPMENT_URL, params={"search": "bench"}, headers=staff)  # case-insensitive
    assert by_search.json()["total"] == 1
    assert by_search.json()["items"][0]["name"] == "Bench Press"

    by_category = await client.get(EQUIPMENT_URL, params={"category": "Cardio"}, headers=staff)
    assert by_category.json()["total"] == 1


# --- Pagination envelope ---

async def test_pagination_envelope(client, users, auth_header):
    for i in range(3):
        await _create(client, auth_header, users, name=f"Item {i}")
    staff = auth_header(users[Role.staff])

    page1 = await client.get(EQUIPMENT_URL, params={"skip": 0, "limit": 2}, headers=staff)
    body1 = page1.json()
    assert body1["total"] == 3
    assert len(body1["items"]) == 2
    assert body1["has_next"] is True

    page2 = await client.get(EQUIPMENT_URL, params={"skip": 2, "limit": 2}, headers=staff)
    body2 = page2.json()
    assert body2["total"] == 3
    assert len(body2["items"]) == 1
    assert body2["has_next"] is False         # last page


# --- Soft delete ---

async def test_soft_delete_hides_from_reads(client, users, auth_header):
    a = await _create(client, auth_header, users, name="A")
    await _create(client, auth_header, users, name="B")

    # Delete is admin-only: staff is rejected.
    staff_try = await client.delete(f"{EQUIPMENT_URL}{a['id']}", headers=auth_header(users[Role.staff]))
    assert staff_try.status_code == 403

    deleted = await client.delete(f"{EQUIPMENT_URL}{a['id']}", headers=auth_header(users[Role.admin]))
    assert deleted.status_code == 204

    # Gone from detail (404) and from the list (only B remains) — the row still
    # exists in the table, but reads filter deleted_at IS NULL.
    gone = await client.get(f"{EQUIPMENT_URL}{a['id']}", headers=auth_header(users[Role.staff]))
    assert gone.status_code == 404

    listing = await client.get(EQUIPMENT_URL, headers=auth_header(users[Role.staff]))
    body = listing.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "B"
