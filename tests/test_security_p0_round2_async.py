"""Round 2 budget tests: concurrency offload, uploads, registration, turn_index."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from typing import Any

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.config import get_settings
from backend.app.database import get_session
from backend.app.main import app
from backend.app.models.session import SocraticTurnLog
from backend.app.services.gemini_router import get_gemini_router
from tests.security_round2_api import SlowStubRouter, post_turn, register_user

pytest_plugins = ["tests.security_round2_helpers"]


async def test_ten_concurrent_turns_overlap_when_llm_is_offloaded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """10 parallel /turn calls with a 1s mocked LLM should finish in ~1-2s, not ~10s."""
    get_settings.cache_clear()
    monkeypatch.setenv("TURNS_PER_USER_PER_HOUR", "50")
    monkeypatch.setenv("TURNS_PER_USER_PER_DAY", "200")
    monkeypatch.setenv("GLOBAL_TURNS_PER_DAY", "500")
    get_settings.cache_clear()

    db_path = tmp_path / "concurrent_budget.db"
    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
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
    app.dependency_overrides[get_gemini_router] = lambda: SlowStubRouter()

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            timeout=30.0,
        ) as client:
            headers = await register_user(client, "concurrent@test.com")
            warm = await post_turn(client, headers, text="warmup")
            assert warm.status_code == 200, warm.text

            started = time.perf_counter()
            results = await asyncio.gather(
                *[post_turn(client, headers, text=f"c{i}") for i in range(10)]
            )
            elapsed = time.perf_counter() - started

        assert all(r.status_code == 200 for r in results), [
            (r.status_code, r.text) for r in results
        ]
        assert elapsed < 4.0, f"Expected overlapped LLM work (~1-2s), got {elapsed:.2f}s"
        assert elapsed >= 0.9, f"Stub should sleep ~1s; got {elapsed:.2f}s"
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
        await test_engine.dispose()


async def test_upload_daily_cap_returns_429(
    budget_client: tuple[AsyncClient, Any],
) -> None:
    """RAG upload exceeding UPLOADS_PER_USER_PER_DAY returns 429."""
    import pymupdf as fitz

    client, _ = budget_client
    headers = await register_user(client, "uploader@test.com")

    def _pdf(label: str) -> bytes:
        doc = fitz.open()
        doc.new_page().insert_text((40, 40), f"chapter text {label}")
        data = doc.tobytes()
        doc.close()
        return data

    for i in range(2):
        resp = await client.post(
            "/api/rag/upload",
            files={"file": (f"c{i}.pdf", _pdf(str(i)), "application/pdf")},
            data={"title": f"Chapter {i}"},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text

    blocked = await client.post(
        "/api/rag/upload",
        files={"file": ("c2.pdf", _pdf("2"), "application/pdf")},
        data={"title": "Chapter 2"},
        headers=headers,
    )
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


async def test_registration_disabled_and_ip_throttle(
    budget_client: tuple[AsyncClient, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ALLOW_PUBLIC_REGISTRATION=false blocks signup; IP daily cap returns 429."""
    client, _ = budget_client

    for i in range(3):
        assert (
            await client.post(
                "/api/auth/register",
                json={
                    "email": f"ip{i}@test.com",
                    "password": "Password123!",
                    "full_name": f"IP {i}",
                },
            )
        ).status_code == 201

    throttled = await client.post(
        "/api/auth/register",
        json={
            "email": "ip_over@test.com",
            "password": "Password123!",
            "full_name": "IP Over",
        },
    )
    assert throttled.status_code == 429

    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", "false")
    get_settings.cache_clear()
    closed = await client.post(
        "/api/auth/register",
        json={
            "email": "invite_only@test.com",
            "password": "Password123!",
            "full_name": "Closed",
        },
    )
    assert closed.status_code == 403
    assert "registration" in closed.json()["detail"].lower()


async def test_turn_index_unique_and_monotonic(
    budget_client: tuple[AsyncClient, Any],
) -> None:
    """Turns use unique (session_id, turn_index) allocated via max+1, not row counts."""
    client, session_maker = budget_client
    headers = await register_user(client, "turnidx@test.com")

    first = await post_turn(client, headers, text="first")
    assert first.status_code == 200
    session_id = first.json()["session_id"]

    second = await client.post(
        "/api/tutor/turn",
        json={
            "track": "MATH",
            "session_id": session_id,
            "student_input": "second",
            "chat_mode": True,
        },
        headers=headers,
    )
    assert second.status_code == 200

    async with session_maker() as session:
        rows = list(
            (
                await session.exec(
                    select(SocraticTurnLog)
                    .where(SocraticTurnLog.session_id == session_id)
                    .order_by(SocraticTurnLog.turn_index)  # type: ignore[arg-type]
                )
            ).all()
        )
    assert [r.turn_index for r in rows] == [1, 2]

    table_args = getattr(SocraticTurnLog, "__table_args__", ())
    assert table_args, "Expected UniqueConstraint on SocraticTurnLog"
