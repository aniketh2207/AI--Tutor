"""Round 2.5 hardening: prod env fail-closed, budget order, AST leak/solved, IP, atomic quota."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.config import Settings, get_settings
from backend.app.database import get_session
from backend.app.main import app
from backend.app.models.rate_limit import RateLimitBucket
from backend.app.schemas.socratic import NeuralSocraticDraft
from backend.app.services.gemini_router import get_gemini_router
from backend.app.services.rate_limit_service import (
    SCOPE_GLOBAL_TURNS_DAY,
    GLOBAL_SUBJECT,
    client_ip_from_request,
    consume_quota,
    day_window_start,
)
from backend.app.startup_validation import validate_production_settings
from backend.app.symbolic.ast_verifier import verify_code_turn
from tests.security_round2_api import FastStubRouter, post_turn, register_user


def test_dockerfile_sets_app_env_production() -> None:
    """Deployed image must set APP_ENV=production so startup validation runs."""
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "APP_ENV=production" in text or 'APP_ENV="production"' in text


def test_validate_treats_non_dev_test_as_production() -> None:
    """Anything other than development/test must fail-closed on insecure secrets."""
    for env_name in ("staging", "production", "prod", "cloud", ""):
        insecure = Settings(
            app_env=env_name,
            debug=False,
            jwt_secret_key="socratic-tutor-dev-secret-key-change-in-prod-32b",
            google_client_id="123456789-real.apps.googleusercontent.com",
        )
        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
            validate_production_settings(insecure)

    # Explicit local / test envs remain permissive
    for env_name in ("development", "dev", "test", "testing"):
        validate_production_settings(
            Settings(
                app_env=env_name,
                debug=True,
                jwt_secret_key="socratic-tutor-dev-secret-key-change-in-prod-32b",
                google_client_id="mock-google-client-id.apps.googleusercontent.com",
            )
        )


def test_client_ip_uses_last_xff_entry_not_client_spoofed_first() -> None:
    """Cloud Run appends the real client at the end; ignore client-supplied prefix."""
    request = MagicMock()
    request.headers = {"x-forwarded-for": "1.1.1.1, 8.8.8.8, 35.191.0.1"}
    request.client = MagicMock(host="127.0.0.1")
    assert client_ip_from_request(request) == "35.191.0.1"

    # Spoofed first hop must not become the rate-limit subject key
    spoof_a = MagicMock()
    spoof_a.headers = {"x-forwarded-for": "10.0.0.1, 35.191.0.1"}
    spoof_a.client = MagicMock(host="127.0.0.1")
    spoof_b = MagicMock()
    spoof_b.headers = {"x-forwarded-for": "10.0.0.99, 35.191.0.1"}
    spoof_b.client = MagicMock(host="127.0.0.1")
    assert client_ip_from_request(spoof_a) == client_ip_from_request(spoof_b)


def test_ast_only_always_checks_hint_leak_and_can_solve_structurally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With EXECUTION_DISABLED, still reject leaked hints; valid AST can be solved."""
    monkeypatch.setenv("ENABLE_CODE_EXECUTION", "false")
    get_settings.cache_clear()

    valid_code = (
        "def sum_elements(nums):\n"
        "    total = 0\n"
        "    for x in nums:\n"
        "        total += x\n"
        "    return total\n"
    )
    rules = {
        "function_name": "sum_elements",
        "required_ast_nodes": ["FunctionDef", "For", "Return"],
        "forbidden_ast_nodes": ["While"],
        "forbidden_calls": ["sum"],
        "test_cases": [{"input": [[1, 2, 3]], "expected": 6}],
        "chat_mode": False,
    }

    leaked = NeuralSocraticDraft(
        student_intent_summary="Student wrote a valid function.",
        student_symbolic_claim=valid_code,
        is_final_goal_reached_claim=False,
        socratic_question=(
            "Try this instead:\n```python\ndef sum_elements(nums):\n    return sum(nums)\n```"
        ),
    )
    leak_verdict, leak_solved = verify_code_turn(
        draft=leaked, problem_rules=rules, student_raw_input=valid_code
    )
    assert leak_verdict.passed is False
    assert leak_verdict.answer_leaked_in_hint is True
    assert leak_solved is False

    clean = NeuralSocraticDraft(
        student_intent_summary="Student wrote a valid function.",
        student_symbolic_claim=valid_code,
        is_final_goal_reached_claim=True,
        socratic_question="Your structure looks solid — what edge case would you test next?",
    )
    ok_verdict, ok_solved = verify_code_turn(
        draft=clean, problem_rules=rules, student_raw_input=valid_code
    )
    assert ok_verdict.passed is True
    assert ok_verdict.student_step_correct is True
    assert ok_solved is True
    assert "EXECUTION_DISABLED" in ok_verdict.symbolic_rule_checked


@pytest.fixture()
async def budget_client_r25(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AsyncClient, None]:
    """Isolated DB with low hourly + global caps for budget-order tests."""
    get_settings.cache_clear()
    monkeypatch.setenv("TURNS_PER_USER_PER_HOUR", "3")
    monkeypatch.setenv("TURNS_PER_USER_PER_DAY", "100")
    monkeypatch.setenv("GLOBAL_TURNS_PER_DAY", "5")
    monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", "true")
    monkeypatch.setenv("REGISTRATIONS_PER_IP_PER_DAY", "50")
    get_settings.cache_clear()

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def override() -> AsyncGenerator[AsyncSession, None]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_gemini_router] = lambda: FastStubRouter()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    await engine.dispose()


async def test_user_a_hourly_spam_does_not_burn_global_for_user_b(
    budget_client_r25: AsyncClient,
) -> None:
    """Rejected over-limit turns must not increment the global daily counter."""
    client = budget_client_r25
    headers_a = await register_user(client, "spam_a@test.com", "Spam A")
    headers_b = await register_user(client, "ok_b@test.com", "Ok B")

    for i in range(3):
        assert (await post_turn(client, headers_a, text=f"a{i}")).status_code == 200
    for i in range(8):
        assert (await post_turn(client, headers_a, text=f"spam{i}")).status_code == 429

    # Global budget was 5; if A burned it via 429 spam, B would get 503.
    for i in range(2):
        resp = await post_turn(client, headers_b, text=f"b{i}")
        assert resp.status_code == 200, resp.text


async def test_consume_quota_is_atomic_under_concurrency(tmp_path: Any) -> None:
    """Parallel consume_quota calls must not overshoot the limit via lost updates."""
    from fastapi import HTTPException

    db_path = tmp_path / "atomic_quota.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    window = day_window_start(datetime.now(timezone.utc))
    limit = 20

    async def one_consume() -> bool:
        async with maker() as session:
            try:
                await consume_quota(
                    session,
                    scope="atomic_test",
                    subject_key="user-1",
                    window_start=window,
                    limit=limit,
                    retry_after_seconds=60,
                    detail="capped",
                )
                return True
            except HTTPException:
                return False

    results = await asyncio.gather(*[one_consume() for _ in range(40)])
    assert sum(1 for ok in results if ok) == limit

    async with maker() as session:
        row = (
            await session.exec(
                select(RateLimitBucket).where(
                    RateLimitBucket.scope == "atomic_test",
                    RateLimitBucket.subject_key == "user-1",
                    RateLimitBucket.window_start == window,
                )
            )
        ).first()
    assert row is not None
    assert row.count == limit
    await engine.dispose()
