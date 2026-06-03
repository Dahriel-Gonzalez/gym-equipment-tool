"""Aggregates every v1 endpoint router into a single `api_router`.

main.py mounts this once under /api/v1, so each endpoint module stays unaware of
the version prefix. Add new resource routers here as you build them.
"""
from fastapi import APIRouter

from app.api.v1.endpoints import auth, equipment, issues, users

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(equipment.router, prefix="/equipment", tags=["equipment"])
api_router.include_router(issues.router, prefix="/issues", tags=["issues"])

# Wire the rest as their endpoint modules get built:
# from app.api.v1.endpoints import comments
# api_router.include_router(issues.router, prefix="/issues", tags=["issues"])
# api_router.include_router(comments.router, prefix="/issues", tags=["comments"])
