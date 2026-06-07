"""Async Redis cache: the client singleton + small JSON helpers.

This is the only module that owns the Redis client, the same way db/session.py
owns the database engine. Everything else (currently just the equipment list
endpoint) talks to the cache through the helpers here, never to redis directly.

Design rule: the cache FAILS OPEN. Every operation is wrapped so that if Redis
is unreachable or misbehaving, the helper logs a warning and behaves as a miss
(reads return None, writes/invalidations are no-ops). A request must never 500
because the cache is down — at worst it falls back to hitting Postgres.
"""
from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from app.config import settings
from app.core.logging import logger

# Module-level singleton. redis.asyncio.from_url builds a connection POOL behind
# this client, so concurrent requests share/borrow connections — we don't open a
# socket per call. decode_responses=True makes reads come back as str, not bytes,
# which is what json.loads wants.
_redis: aioredis.Redis = aioredis.from_url(
    settings.REDIS_URL,
    encoding="utf-8",
    decode_responses=True,
)


async def get_json(key: str) -> Any | None:
    """Return the cached value at `key` (parsed from JSON), or None on a miss /
    any Redis error. A None here is indistinguishable from "not cached" by design
    — the caller just proceeds to the database."""
    try:
        raw = await _redis.get(key)
    except Exception:  # noqa: BLE001 — fail open: any cache fault is a miss.
        logger.warning("cache_get_failed", key=key)
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Corrupt/garbage value — treat as a miss and let it be overwritten.
        logger.warning("cache_decode_failed", key=key)
        return None


async def set_json(key: str, value: Any, ttl_seconds: int) -> None:
    """Serialize `value` to JSON and store it at `key` with a TTL (in seconds).

    The TTL is the safety net for the list cache: even if an invalidation is ever
    missed, a stale entry can only live `ttl_seconds` before Redis expires it.
    """
    try:
        await _redis.set(key, json.dumps(value), ex=ttl_seconds)
    except (TypeError, ValueError):
        # value wasn't JSON-serializable — a programming error, not a cache fault.
        # Skip caching rather than crash the request; surface it in the logs.
        logger.warning("cache_set_unserializable", key=key)
    except Exception:  # noqa: BLE001 — fail open on Redis errors.
        logger.warning("cache_set_failed", key=key)


async def delete_prefix(prefix: str) -> None:
    """Delete every key beginning with `prefix`.

    Used to invalidate a whole family of cached pages at once: one equipment
    write can't know which of the many filter/pagination permutations are cached,
    so it blows away all `equipment:list:*` keys. SCAN (not KEYS) iterates the
    keyspace in cursor-sized chunks without blocking Redis on a big database.
    """
    try:
        async for key in _redis.scan_iter(match=f"{prefix}*"):
            await _redis.delete(key)
    except Exception:  # noqa: BLE001 — fail open: a failed purge just leaves
        # entries to expire via their TTL; it can't break the write that triggered it.
        logger.warning("cache_delete_prefix_failed", prefix=prefix)


async def close() -> None:
    """Close the client's connection pool. Call on application shutdown so we
    don't leak connections; safe to call even if Redis was never reached."""
    try:
        await _redis.aclose()
    except Exception:  # noqa: BLE001
        logger.warning("cache_close_failed")
