"""Pytest fixtures for Round 2 API-budget tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.config import get_settings
from backend.app.database import get_session
from backend.app.main import app
from backend.app.services.gemini_router import get_gemini_router
from tests.security_round2_api import FastStubRouter


@pytest.fixture()
async def budget_client(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[tuple[AsyncClient, async_sessionmaker[AsyncSession]], None]:
    """Isolated shared-memory DB + stub Gemini with tight budget defaults."""
    get_settings.cache_clear()
    monkeypatch.setenv("TURNS_PER_USER_PER_HOUR", "3")
    monkeypatch.setenv("TURNS_PER_USER_PER_DAY", "100")
    monkeypatch.setenv("UPLOADS_PER_USER_PER_DAY", "2")
    monkeypatch.setenv("GLOBAL_TURNS_PER_DAY", "1000")
    monkeypatch.setenv("REGISTRATIONS_PER_IP_PER_DAY", "3")
    monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", "true")
    get_settings.cache_clear()

    test_engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    session_maker = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_gemini_router] = lambda: FastStubRouter()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client, session_maker

    app.dependency_overrides.clear()
    get_settings.cache_clear()
    await test_engine.dispose()
