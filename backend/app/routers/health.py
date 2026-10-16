"""Liveness and readiness probes for Cloud Run / local ops."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.config import get_settings
from backend.app.database import get_session

router = APIRouter(tags=["System"])


@router.get("/livez")
async def livez() -> dict[str, str]:
    """Cheap process liveness probe (no dependency checks)."""
    return {"status": "ok"}


@router.get("/health")
async def readiness(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    """Readiness: verify the database answers a trivial query."""
    settings = get_settings()
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc
    return {
        "status": "healthy",
        "service": settings.app_name,
        "primary_model": settings.gemini_primary_model,
    }
