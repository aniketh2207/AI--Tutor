"""Async SQLModel database engine, session factory, and pgvector initialization."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.config import get_settings
import backend.app.models  # noqa: F401 - ensure all SQLModel tables are registered


def normalize_async_db_url(raw_url: str) -> str:
    """Normalize PostgreSQL or SQLite URLs to their async SQLAlchemy driver variants.

    Strips whitespace and accidental surrounding quotes (common when secrets are
    uploaded via PowerShell ``echo`` / ``Write-Output`` pipelines).
    """
    cleaned = raw_url.strip().strip('"').strip("'").strip()
    if cleaned.startswith("postgres://"):
        return cleaned.replace("postgres://", "postgresql+psycopg://", 1)
    if cleaned.startswith("postgresql://"):
        return cleaned.replace("postgresql://", "postgresql+psycopg://", 1)
    if cleaned.startswith("sqlite:///"):
        return cleaned.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return cleaned


def build_async_engine(db_url: str | None = None) -> AsyncEngine:
    """Create an AsyncEngine configured for Neon PostgreSQL or SQLite fallback."""
    settings = get_settings()
    resolved_url = normalize_async_db_url(db_url or settings.database_url)
    connect_args: dict[str, object] = {}
    if resolved_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    return create_async_engine(
        resolved_url,
        echo=False,
        future=True,
        connect_args=connect_args,
    )


engine: AsyncEngine = build_async_engine()

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db(target_engine: AsyncEngine | None = None) -> None:
    """Initialize database schema and enable pgvector on PostgreSQL."""
    active_engine = target_engine or engine
    async with active_engine.begin() as conn:
        if active_engine.dialect.name == "postgresql":
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async SQLModel database session."""
    async with async_session_factory() as session:
        yield session
