"""Rate limiting: the shared slowapi Limiter, its limits, and the 429 handler.

Two layers of protection:
  1. A GLOBAL default limit applied to every route via SlowAPIMiddleware, keyed
     by client IP. This is a coarse anti-flood backstop — it covers every route a
     member (or anyone) can call, including reads, with no per-route wiring.
  2. Tighter PER-USER limits on the abuse-prone write endpoints (creating issues
     and comments), applied with an explicit @limiter.limit(..., key_func=user_key)
     decorator. Keyed by the authenticated user so one account's spamming doesn't
     throttle unrelated users sharing an IP (e.g. the gym's network).
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.errors import HUMAN_MESSAGES, RATE_LIMIT_EXCEEDED

# --- Limits (format "<count>/<period>") ---
# Coarse per-IP flood backstop on EVERY route (applied via middleware).
GLOBAL_LIMIT = "200/minute"
# Pre-auth, per IP.
LOGIN_LIMIT = "5/minute"        # password guessing: a human login never needs more.
REGISTER_LIMIT = "10/hour"      # caps accounts mintable per origin — the abuse root.
REFRESH_LIMIT = "30/minute"     # generous; a real client refreshes occasionally.
# Authenticated writes, per user (the spam vectors a fresh member can hit).
ISSUE_CREATE_LIMIT = "20/minute"
COMMENT_CREATE_LIMIT = "30/minute"


def user_key(request: Request) -> str:
    """Rate-limit bucket for authenticated routes: the user id if known, else IP.

    get_current_user stashes request.state.current_user_id during dependency
    resolution, which runs BEFORE the @limiter.limit check inside the route — so
    by the time this is consulted the id is present for any authenticated call.
    Unauthenticated calls (or a failed auth) fall back to the client IP.
    """
    user_id = getattr(request.state, "current_user_id", None)
    if user_id is not None:
        return f"user:{user_id}"
    return get_remote_address(request)


# Default key_func is the client IP, which is correct for the global backstop and
# for the pre-auth routes. Per-user routes override key_func to user_key.
limiter = Limiter(key_func=get_remote_address, default_limits=[GLOBAL_LIMIT])


def _retry_after_seconds(exc: RateLimitExceeded) -> int | None:
    """Best-effort window length (seconds) for the Retry-After header.

    The matched limit hangs off the exception, but its shape differs between the
    decorator path and the middleware path, so try both nestings and give up
    quietly if neither fits (a missing Retry-After is harmless).
    """
    limit = getattr(exc, "limit", None)
    for candidate in (getattr(limit, "limit", None), limit):
        try:
            return int(candidate.get_expiry())
        except Exception:  # noqa: BLE001 — header is optional; never fail the response.
            continue
    return None


async def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Render a tripped limit in our standard error envelope, with Retry-After
    when we can derive it. Registered for RateLimitExceeded specifically in
    main.py so it wins over the generic HTTPException handler."""
    response = JSONResponse(
        status_code=429,
        content={
            "error": RATE_LIMIT_EXCEEDED,
            "message": HUMAN_MESSAGES[RATE_LIMIT_EXCEEDED],
        },
    )
    retry_after = _retry_after_seconds(exc)
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    return response
