"""Reusable pagination: the query-param dependency and the response envelope.

PaginationParams is a dependency that captures ?skip=&limit= once, so every list
endpoint declares `params: PaginationParams = Depends()` instead of repeating two
Query args. PaginatedResponse[T] is the generic envelope that wraps the page with
total/has_next so clients can build paging UIs without extra requests.
"""
from __future__ import annotations

from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")


class PaginationParams:
    """Shared ?skip=&limit= query params. Used as a dependency: Depends().

    A plain class (not a Pydantic model) because FastAPI reads the __init__
    signature to build the query params, and the bounds live on the Query()s.
    """

    def __init__(
        self,
        skip: int = Query(0, ge=0, description="Rows to skip (offset)."),
        limit: int = Query(20, ge=1, le=100, description="Max rows to return."),
    ) -> None:
        self.skip = skip
        self.limit = limit


class PaginatedResponse(BaseModel, Generic[T]):
    """Envelope for a page of results.

    `total` is the count across ALL matching rows (ignoring skip/limit); the
    endpoint gets it from a COUNT query. `has_next` is derived, not stored by the
    caller — see create().
    """

    items: list[T]
    total: int
    skip: int
    limit: int
    has_next: bool

    @classmethod
    def create(
        cls, items: list[T], total: int, *, skip: int, limit: int
    ) -> "PaginatedResponse[T]":
        """Build an envelope, computing has_next from how far into `total` this
        page reaches. Using len(items) (not skip+limit) is correct even on a
        short final page."""
        return cls(
            items=items,
            total=total,
            skip=skip,
            limit=limit,
            has_next=skip + len(items) < total,
        )
