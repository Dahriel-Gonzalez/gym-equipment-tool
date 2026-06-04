"""Comment endpoints, nested under /issues/{issue_id}/comments.

Two access rules converge here:
  - VISIBILITY: members see only public comments; staff+ see internal ones too.
    Enforced by passing include_internal to the query (filtered in SQL).
  - AUTHORSHIP: edit is author-only; delete is author-or-manager.
Plus: to comment on an issue at all, you must be able to ACCESS that issue
(reporter or staff+) — the same row-level rule the issue routes use.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import (
    ensure_can_access_issue,
    is_manager_or_above,
    is_staff_or_above,
)
from app.crud import comment as comment_crud
from app.crud import issue as issue_crud
from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.comment import Comment
from app.models.issue import Issue
from app.models.user import User
from app.schemas.comment import CommentCreate, CommentResponse, CommentUpdate

router = APIRouter()


async def _get_issue_or_404(db: AsyncSession, issue_id: UUID) -> Issue:
    issue = await issue_crud.get(db, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="ISSUE_NOT_FOUND")
    return issue


async def _get_comment_or_404(db: AsyncSession, issue_id: UUID, comment_id: UUID) -> Comment:
    comment = await comment_crud.get(db, comment_id)
    # Also confirm the comment actually belongs to the issue in the path.
    if comment is None or comment.issue_id != issue_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="COMMENT_NOT_FOUND")
    return comment


@router.get("/{issue_id}/comments/", response_model=list[CommentResponse])
async def list_comments(
    issue_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Comment]:
    """List an issue's comments. Members get public comments only."""
    issue = await _get_issue_or_404(db, issue_id)
    ensure_can_access_issue(current_user, issue)
    return await comment_crud.get_multi_for_issue(
        db,
        issue_id,
        include_internal=is_staff_or_above(current_user),
        skip=skip,
        limit=limit,
    )


@router.post(
    "/{issue_id}/comments/",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_comment(
    issue_id: UUID,
    payload: CommentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Comment:
    """Add a comment to an issue. Only staff+ may mark a comment internal."""
    issue = await _get_issue_or_404(db, issue_id)
    ensure_can_access_issue(current_user, issue)
    if payload.is_internal and not is_staff_or_above(current_user):
        # A member explicitly asked for an internal note — reject rather than
        # silently downgrade, so their intent isn't quietly changed.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="CANNOT_CREATE_INTERNAL_COMMENT"
        )
    return await comment_crud.create(
        db,
        issue_id=issue_id,
        author_id=current_user.id,
        body=payload.body,
        is_internal=payload.is_internal,
    )


@router.patch("/{issue_id}/comments/{comment_id}", response_model=CommentResponse)
async def edit_comment(
    issue_id: UUID,
    comment_id: UUID,
    payload: CommentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Comment:
    """Edit a comment's body. Author only — not even managers edit others' words."""
    comment = await _get_comment_or_404(db, issue_id, comment_id)
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="NOT_COMMENT_AUTHOR")
    return await comment_crud.update(db, comment, payload)


@router.delete(
    "/{issue_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_comment(
    issue_id: UUID,
    comment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a comment. Author or manager+ (managers moderate)."""
    comment = await _get_comment_or_404(db, issue_id, comment_id)
    if comment.author_id != current_user.id and not is_manager_or_above(current_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="FORBIDDEN")
    await comment_crud.delete(db, comment)
    return None
