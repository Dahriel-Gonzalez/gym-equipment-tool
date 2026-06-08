"""Rate-limit tests.

The global autouse `_disable_rate_limit` fixture (conftest.py) turns the limiter
OFF for the rest of the suite so ordinary tests aren't throttled. These tests are
the exception: the `rate_limiter_on` fixture flips it back ON (and resets the
in-memory counters) just for here, so we can prove the throttle actually fires.

Login is the surface under test (5/minute per IP). Invalid credentials are fine —
slowapi counts every request that reaches the route *before* the endpoint runs,
so a burst of failed logins increments the same counter and trips the limit.
"""
from __future__ import annotations

import uuid

import pytest

from app.core.rate_limit import limiter
from app.models.user import Role

LOGIN_URL = "/api/v1/auth/login"
ISSUES_URL = "/api/v1/issues/"


@pytest.fixture
def rate_limiter_on():
    """Enable the limiter with a clean counter for one test, then disable it again.

    Requested explicitly by the test, so it runs AFTER the autouse disable fixture
    and wins. reset() clears MemoryStorage so counts don't leak in or out.
    """
    limiter.reset()
    limiter.enabled = True
    yield
    limiter.enabled = False
    limiter.reset()


async def test_login_rate_limited_after_threshold(client, rate_limiter_on):
    """The 6th login within the window is blocked with 429, in our error envelope."""
    creds = {"username": "nobody@test.com", "password": "wrong-password"}

    # LOGIN_LIMIT is "5/minute": the first 5 reach the endpoint and fail auth (401).
    for attempt in range(5):
        resp = await client.post(LOGIN_URL, data=creds)
        assert resp.status_code == 401, f"attempt {attempt} should pass the limiter"

    # The 6th exceeds the limit and is rejected before the endpoint even runs.
    blocked = await client.post(LOGIN_URL, data=creds)
    assert blocked.status_code == 429
    assert blocked.json()["error"] == "RATE_LIMIT_EXCEEDED"
    # The handler injects Retry-After so a client knows when it may try again.
    assert "retry-after" in {k.lower() for k in blocked.headers}


async def test_limiter_disabled_by_default(client):
    """Sanity check on the autouse fixture: with the limiter off (the default for
    the suite), a burst well past the threshold is never throttled."""
    creds = {"username": "nobody@test.com", "password": "wrong-password"}
    for _ in range(8):
        resp = await client.post(LOGIN_URL, data=creds)
        assert resp.status_code == 401  # always reaches the endpoint; never 429


async def test_issue_creation_rate_limited_per_user(client, users, auth_header, rate_limiter_on):
    """A signed-up member is throttled on issue creation (ISSUE_CREATE_LIMIT, 20/min),
    keyed by user. A bogus equipment_id 404s, but the limiter counts each request
    before the endpoint runs — so the 21st within the window is blocked with 429."""
    headers = auth_header(users[Role.member])
    # Valid-shaped body (passes schema, so the request reaches the limited route);
    # the equipment doesn't exist, so the endpoint itself would answer 404.
    body = {
        "equipment_id": str(uuid.uuid4()),
        "title": "Title here",
        "description": "Ten chars plus.",
    }
    for i in range(20):
        resp = await client.post(ISSUES_URL, json=body, headers=headers)
        assert resp.status_code == 404, (i, resp.status_code, resp.text)

    blocked = await client.post(ISSUES_URL, json=body, headers=headers)
    assert blocked.status_code == 429
    assert blocked.json()["error"] == "RATE_LIMIT_EXCEEDED"


async def test_issue_limit_is_per_user_not_global(client, users, auth_header, rate_limiter_on):
    """The issue limit is keyed by user: a second member has an independent budget,
    so one account exhausting its limit doesn't lock others out."""
    body = {
        "equipment_id": str(uuid.uuid4()),
        "title": "Title here",
        "description": "Ten chars plus.",
    }
    # Member burns through their 20/min budget (21st blocked).
    member_headers = auth_header(users[Role.member])
    for _ in range(20):
        await client.post(ISSUES_URL, json=body, headers=member_headers)
    assert (await client.post(ISSUES_URL, json=body, headers=member_headers)).status_code == 429

    # A different user (staff) is unaffected — their own bucket is still empty.
    staff_resp = await client.post(ISSUES_URL, json=body, headers=auth_header(users[Role.staff]))
    assert staff_resp.status_code == 404  # reaches the endpoint, not rate-limited
