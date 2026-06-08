# Gym Equipment API

A multi-role issue-tracking system for gym equipment. Backend scoped to a single gym. Members log issues against equipment; staff triage and comment; managers resolve/close and manage inventory; admins manage users.

Built with **FastAPI**, **async SQLAlchemy 2.x**, and **PostgreSQL**.

---

## Features

- **Role-based access** — `member → staff → manager → admin`, enforced with a
  `require_role(*roles)` dependency plus row-level ownership checks (a member can
  only touch their own issues).
- **Issue lifecycle state machine** — transitions are centralized in `IssueService`
  (`open → in_progress → resolved → closed`, with reopen paths). Resolving stamps
  `resolved_at`/`resolved_by`; a critical issue auto-flips its equipment to
  `under_maintenance`, and releases it when cleared.
- **JWT auth** — short-lived access tokens + longer refresh tokens (`python-jose`),
  passwords hashed with bcrypt.
- **Comments with visibility rules** — `is_internal` notes are returned to staff+
  only; members get filtered responses.
- **Pagination** on every list endpoint (`total` / `has_next` envelope).
- **Redis caching** of the equipment list (cache-aside, invalidated on write).
- **Rate limiting** (`slowapi`) — a global per-IP backstop on every route, plus
  tighter per-user limits on the abuse-prone write endpoints (issue/comment
  creation) and per-IP limits on the auth endpoints.
- **Structured logging** (`structlog`) — JSON in production, pretty console in
  debug. A per-request `request_id` is bound into a contextvar so every log line
  (incl. domain events like `issue_status_changed`) carries it automatically.
- **CSV export** of issue history (`GET /issues/export`) for offline review.
- **Centralized error envelope** — every error is `{"error": <CODE>, "message": <sentence>}`.

## Tech stack

| Concern        | Choice                                             |
|----------------|----------------------------------------------------|
| Framework      | FastAPI                                            |
| ORM            | SQLAlchemy 2.x (async, `asyncpg`)                  |
| Database       | PostgreSQL                                         |
| Migrations     | Alembic (async `env.py`)                           |
| Validation     | Pydantic v2 + `pydantic-settings`                  |
| Auth           | JWT (`python-jose`) + bcrypt (`passlib`)           |
| Cache / limits | Redis + `slowapi`                                  |
| Logging        | `structlog`                                        |
| Tests          | `pytest` + `pytest-asyncio` + `httpx`              |

## Architecture

A strict layering discipline — each layer has one job, and depends only on the
layer below it:

```
models → schemas → crud → services → endpoints
```

- **models/** — SQLAlchemy ORM; the database shape.
- **schemas/** — Pydantic request/response contracts (never expose ORM objects).
- **crud/** — raw queries, no business logic.
- **services/** — business rules (the issue state machine lives here, never in CRUD).
- **endpoints/** — HTTP only; call services, return schemas.

```
app/
├── main.py              # app factory, middleware, exception handlers, lifespan
├── config.py            # pydantic-settings (env-driven)
├── dependencies.py      # get_current_user, require_role
├── api/v1/
│   ├── router.py        # mounts all resource routers under /api/v1
│   └── endpoints/       # auth, users, equipment, issues, comments
├── core/                # security, permissions, errors, logging, cache, rate_limit
├── crud/                # data access per resource
├── services/            # issue_service (state machine + side effects)
├── models/              # ORM models
├── schemas/             # Pydantic models
└── db/                  # engine/session, declarative base + mixins
alembic/                 # migrations
tests/                   # pytest suite
```

## Getting started

### Prerequisites

- Python **3.11+**
- Docker (for the Postgres + Redis containers), or your own Postgres/Redis

### 1. Install

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — at minimum set a real SECRET_KEY (e.g. `openssl rand -hex 32`).
```

### 3. Start the datastores

```bash
docker compose up -d postgres redis
```

Postgres is published on host port **5433** (to avoid clashing with a native
Postgres on 5432); Redis on **6379**. Both URLs are pre-set in `.env.example`.

### 4. Run migrations

```bash
alembic upgrade head
```

### 5. Run the app

```bash
uvicorn app.main:app --reload
```

- Interactive API docs: **http://localhost:8000/docs**
- Health probe (checks DB connectivity): **http://localhost:8000/health**

> **First admin:** on startup the app seeds an admin from `FIRST_ADMIN_EMAIL` /
> `FIRST_ADMIN_PASSWORD` if no user with that email exists yet (idempotent — a
> no-op once it's there). **Before your first run, change `FIRST_ADMIN_EMAIL` in
> `.env` to the email of whoever should be the admin** (e.g. the gym's manager),
> and set a strong `FIRST_ADMIN_PASSWORD` — a placeholder password is seeded but
> logs a warning. That admin can then manage everyone else via
> `PATCH /users/{id}/role`. (`POST /auth/register` always creates a `member`.)

## API overview

All routes are under `/api/v1`. Full interactive reference at `/docs`.

| Method | Path | Access |
|--------|------|--------|
| POST | `/auth/register` | public |
| POST | `/auth/login` | public |
| POST | `/auth/refresh` | public |
| POST | `/auth/logout` | public |
| GET · PATCH · POST | `/users/me`, `/users/me/password` | authenticated |
| GET | `/users/{id}` | manager+ |
| GET · PATCH · DELETE | `/users`, `/users/{id}/role`, `/users/{id}` | admin |
| GET | `/equipment`, `/equipment/{id}`, `/equipment/{id}/issues` | authenticated |
| POST · PATCH | `/equipment` | manager+ |
| DELETE | `/equipment/{id}` | admin (soft delete) |
| POST | `/issues` | authenticated (per-user rate limited) |
| GET | `/issues/mine` | authenticated |
| GET | `/issues`, `/issues/export` | staff+ |
| GET · PATCH | `/issues/{id}` | reporter or staff+ |
| PATCH | `/issues/{id}/status`, `/issues/{id}/resolve` | role-gated in the service |
| PATCH | `/issues/{id}/assign` | staff+ |
| DELETE | `/issues/{id}` | admin |
| GET · POST | `/issues/{id}/comments` | issue-accessor (per-user rate limited on POST) |
| PATCH · DELETE | `/issues/{id}/comments/{cid}` | author (delete: author or manager+) |

### Auth flow

```bash
# Register (creates a member)
curl -X POST localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"a@b.com","full_name":"Ada","password":"password123"}'

# Login (form-encoded; returns access + refresh tokens)
curl -X POST localhost:8000/api/v1/auth/login \
  -d 'username=a@b.com&password=password123'

# Use the access token
curl localhost:8000/api/v1/issues/mine -H 'Authorization: Bearer <access_token>'
```

### CSV export

```bash
curl -OJ localhost:8000/api/v1/issues/export \
  -H 'Authorization: Bearer <staff_token>'
# Optional filters: ?status=&severity=&equipment_id=&created_after=&created_before=
```

## Testing

```bash
pytest          # full suite (needs the test database; see below)
```

Tests run against a **separate** database, `gym_equipment_test`, created once:

```bash
docker compose exec postgres psql -U gym -c "CREATE DATABASE gym_equipment_test;"
```

Each test rebuilds the schema in isolation. Redis and the rate limiter are
disabled in tests via autouse fixtures, so the suite needs neither a running
Redis nor real throttling. Override the DB URL with `TEST_DATABASE_URL` if needed.

## Notes

- **Redis is optional for local dev** — the cache fails open (a cache fault
  degrades to a direct DB hit), so the app runs fine without it; you only lose
  caching.
- **Multi-worker rate limiting** uses in-memory counts by default. Point the
  limiter (and cache) at Redis via `REDIS_URL` to share state across workers.
- Configuration is environment-driven; never commit `.env` (only `.env.example`).
