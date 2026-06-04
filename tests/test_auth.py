"""Auth endpoint tests: register, login, refresh.

Login uses form data (OAuth2PasswordRequestForm), so these POST `data=`, not
`json=`. Seeded users (the `users` fixture) all have password 'password123'.
"""
from __future__ import annotations

from app.core.security import hash_password
from app.models.user import Role, User

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"


# --- Register ---

async def test_register_success(client):
    resp = await client.post(
        REGISTER_URL,
        json={"email": "new@test.com", "full_name": "New User", "password": "password123"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "new@test.com"
    assert body["role"] == "member"          # always starts as member
    assert body["is_active"] is True
    assert "id" in body
    assert "hashed_password" not in body      # secret never leaves the API


async def test_register_duplicate_email_409(client, users):
    resp = await client.post(
        REGISTER_URL,
        json={"email": "member@test.com", "full_name": "Dup", "password": "password123"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"] == "EMAIL_ALREADY_REGISTERED"


async def test_register_short_password_422(client):
    resp = await client.post(
        REGISTER_URL,
        json={"email": "x@test.com", "full_name": "X", "password": "short"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "VALIDATION_ERROR"


async def test_register_ignores_role_field(client):
    # `role` isn't in UserCreate, so a client can't self-promote — still a member.
    resp = await client.post(
        REGISTER_URL,
        json={
            "email": "sneaky@test.com",
            "full_name": "Sneaky",
            "password": "password123",
            "role": "admin",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "member"


# --- Login ---

async def test_login_success(client, users):
    resp = await client.post(
        LOGIN_URL, data={"username": "member@test.com", "password": "password123"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


async def test_login_wrong_password_401(client, users):
    resp = await client.post(
        LOGIN_URL, data={"username": "member@test.com", "password": "wrong"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "INVALID_CREDENTIALS"


async def test_login_unknown_email_is_same_error(client, users):
    # Unknown email yields the SAME 401 as a wrong password — no account enumeration.
    resp = await client.post(
        LOGIN_URL, data={"username": "ghost@test.com", "password": "password123"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "INVALID_CREDENTIALS"


async def test_login_inactive_user_403(client, db_session):
    db_session.add(
        User(
            email="inactive@test.com",
            full_name="Inactive",
            hashed_password=hash_password("password123"),
            role=Role.member,
            is_active=False,
        )
    )
    await db_session.commit()
    resp = await client.post(
        LOGIN_URL, data={"username": "inactive@test.com", "password": "password123"}
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "INACTIVE_USER"


# --- Refresh ---

async def test_refresh_success(client, users):
    login = await client.post(
        LOGIN_URL, data={"username": "member@test.com", "password": "password123"}
    )
    refresh_token = login.json()["refresh_token"]
    resp = await client.post(REFRESH_URL, json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert resp.json()["access_token"]


async def test_refresh_rejects_access_token(client, users):
    # The type claim must stop an access token being replayed as a refresh token.
    login = await client.post(
        LOGIN_URL, data={"username": "member@test.com", "password": "password123"}
    )
    access_token = login.json()["access_token"]
    resp = await client.post(REFRESH_URL, json={"refresh_token": access_token})
    assert resp.status_code == 401
    assert resp.json()["error"] == "INVALID_TOKEN"


async def test_refresh_garbage_token_401(client):
    resp = await client.post(REFRESH_URL, json={"refresh_token": "not.a.jwt"})
    assert resp.status_code == 401
    assert resp.json()["error"] == "INVALID_TOKEN"
