"""Round 2 budget tests: per-user turn caps, window reset, isolation, global ceiling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from httpx import AsyncClient
import pytest

from backend.app.config import get_settings
from tests.security_round2_api import post_turn, register_user

pytest_plugins = ["tests.security_round2_helpers"]


async def test_hourly_turn_cap_returns_429_with_retry_after(
    budget_client: tuple[AsyncClient, Any],
) -> None:
    """User exceeding TURNS_PER_USER_PER_HOUR gets 429 + Retry-After + plain message."""
    client, _ = budget_client
    headers = await register_user(client, "hourly@test.com")

    for i in range(3):
        ok = await post_turn(client, headers, text=f"turn {i}")
        assert ok.status_code == 200, ok.text

    blocked = await post_turn(client, headers, text="over the limit")
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
    assert int(blocked.headers["Retry-After"]) >= 1
    detail = blocked.json()["detail"]
    assert isinstance(detail, str)
    assert "limit" in detail.lower() or "try again" in detail.lower()


async def test_hourly_counter_resets_after_window(
    budget_client: tuple[AsyncClient, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After the hourly window advances, the user can turn again."""
    client, _ = budget_client
    headers = await register_user(client, "reset@test.com")

    frozen = {"now": datetime(2026, 10, 16, 10, 15, tzinfo=timezone.utc)}

    def fake_utc_now() -> datetime:
        return frozen["now"]

    monkeypatch.setattr(
        "backend.app.services.rate_limit_service.utc_now",
        fake_utc_now,
    )

    for i in range(3):
        assert (await post_turn(client, headers, text=f"a{i}")).status_code == 200
    assert (await post_turn(client, headers, text="blocked")).status_code == 429

    frozen["now"] = frozen["now"] + timedelta(hours=1)
    resumed = await post_turn(client, headers, text="new window")
    assert resumed.status_code == 200, resumed.text


async def test_two_users_have_independent_turn_counts(
    budget_client: tuple[AsyncClient, Any],
) -> None:
    """User A hitting the hourly cap must not block User B."""
    client, _ = budget_client
    headers_a = await register_user(client, "user_a@test.com", "User A")
    headers_b = await register_user(client, "user_b@test.com", "User B")

    for i in range(3):
        assert (await post_turn(client, headers_a, text=f"a{i}")).status_code == 200
    assert (await post_turn(client, headers_a, text="a-over")).status_code == 429

    ok_b = await post_turn(client, headers_b, text="b still allowed")
    assert ok_b.status_code == 200, ok_b.text


async def test_global_daily_ceiling_returns_503_for_everyone(
    budget_client: tuple[AsyncClient, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When GLOBAL_TURNS_PER_DAY is exhausted, every user gets 503 resting message."""
    client, _ = budget_client
    get_settings.cache_clear()
    monkeypatch.setenv("GLOBAL_TURNS_PER_DAY", "2")
    monkeypatch.setenv("TURNS_PER_USER_PER_HOUR", "50")
    get_settings.cache_clear()

    headers_a = await register_user(client, "global_a@test.com", "GA")
    headers_b = await register_user(client, "global_b@test.com", "GB")

    assert (await post_turn(client, headers_a, text="g1")).status_code == 200
    assert (await post_turn(client, headers_b, text="g2")).status_code == 200

    resting_a = await post_turn(client, headers_a, text="g3")
    resting_b = await post_turn(client, headers_b, text="g4")
    assert resting_a.status_code == 503
    assert resting_b.status_code == 503
    msg = resting_a.json()["detail"].lower()
    assert "resting" in msg and "tomorrow" in msg
