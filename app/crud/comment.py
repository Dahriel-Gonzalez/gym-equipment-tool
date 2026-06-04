"""CRUD (data-access) layer for issue comments.

Reads eager-load `author` (CommentResponse nests UserSummary) to avoid async
lazy-load failures. The list helper takes include_internal so the endpoint can
hide staff-only notes from members at the query level.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.comment import Comment
from app.schemas.comment import CommentUpdate

# author is the only relation CommentResponse nests.
_LOAD_RELATIONS = (selectinload(Comment.author),)


async def get(db: AsyncSession, comment_id: UUID) -> Comment | None:
    """Fetch one comment by id (with author loaded), or None.

    Does NOT filter is_internal — edit/delete need to load any comment regardless
    of visibility.
    """
    stmt = select(Comment).where(Comment.id == comment_id).options(*_LOAD_RELATIONS)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_multi_for_issue(
    db: AsyncSession,
    issue_id: UUID,
    *,
    include_internal: bool,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[Comment], int]:
    """List an issue's comments (oldest-first) + total count. When
    include_internal is False, is_internal comments are excluded at the SQL level.
    """
    base = select(Comment).where(Comment.issue_id == issue_id)
    if not include_internal:
        base = base.where(Comment.is_internal.is_(False))
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = await db.execute(
        base.options(*_LOAD_RELATIONS)
        .order_by(Comment.created_at, Comment.id)  # chronological, stable tiebreaker
        .offset(skip)
        .limit(limit)
    )
    return list(rows.scalars().all()), total


async def create(
    db: AsyncSession,
    *,
    issue_id: UUID,
    author_id: UUID,
    body: str,
    is_internal: bool = False,
) -> Comment:
    """Insert a comment. Takes primitives, not the schema: `is_internal` has
    already been policy-checked against the author's role in the endpoint, so
    this layer just stores what it's given."""
    comment = Comment(
        issue_id=issue_id,
        author_id=author_id,
        body=body,
        is_internal=is_internal,
    )
    db.add(comment)
    try:
        await db.commit()
    except IntegrityError as exc:
        # e.g. issue_id points at a non-existent issue (FK violation).
        await db.rollback()
        raise ValueError("Invalid issue reference") from exc
    return await get(db, comment.id)


async def update(db: AsyncSession, comment: Comment, comment_in: CommentUpdate) -> Comment:
    """Edit a comment's body. `comment` came from get() (author loaded); with
    expire_on_commit=False the relation survives the commit, so return in place."""
    comment.body = comment_in.body
    await db.commit()
    return comment


async def delete(db: AsyncSession, comment: Comment) -> None:
    """Hard-delete a comment."""
    await db.delete(comment)
    await db.commit()
