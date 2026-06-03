"""Model registry.

Importing the four model modules here registers every table on
``Base.metadata``. Anything that needs the full schema — Alembic autogenerate,
``create_all`` in tests — only has to ``import app.models`` to pull them all in.
Without this, autogenerate sees an empty metadata and produces an empty migration.
"""
from app.models.comment import Comment
from app.models.equipment import Equipment, EquipmentStatus
from app.models.issue import Issue, IssueSeverity, IssueStatus
from app.models.user import Role, User

__all__ = [
    "Comment",
    "Equipment",
    "EquipmentStatus",
    "Issue",
    "IssueSeverity",
    "IssueStatus",
    "Role",
    "User",
]
