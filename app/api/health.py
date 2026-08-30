"""
Health and status endpoints.
"""

from fastapi import APIRouter

from app.core.config import settings
from app.storage.database import database

router = APIRouter(
    prefix="/health",
    tags=["health"],
)


@router.get("")
def health_check():
    """Return application health information."""

    return {
        "status": "healthy",
        "app": settings.app_name,
        "database": database.database_path.exists(),
    }


@router.get("/ready")
def readiness_check():
    """Return whether the application is ready."""

    database_ready = database.database_path.exists()

    return {
        "ready": database_ready,
        "database": database_ready,
    }