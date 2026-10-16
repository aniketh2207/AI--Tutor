"""Non-fixture helpers for Round 2 budget HTTP tests."""

from __future__ import annotations

import time
from typing import Any

from httpx import AsyncClient

from backend.app.schemas.socratic import ModelTelemetry, NeuralSocraticDraft


class FastStubRouter:
    """Instant stub Gemini router for rate-limit tests."""

    embedding_dim = 768

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 768 for _ in texts]

    def generate_socratic_draft(
        self,
        prompt: str,
        system_instruction: str | None = None,
        start_tier: int = 0,
    ) -> tuple[NeuralSocraticDraft, ModelTelemetry]:
        _ = (prompt, system_instruction, start_tier)
        draft = NeuralSocraticDraft(
            student_intent_summary="Student is working on a problem.",
            student_symbolic_claim="NONE",
            is_final_goal_reached_claim=False,
            socratic_question="What is the first step you would try?",
        )
        telemetry = ModelTelemetry(
            model_used="gemini-3.1-flash-lite",
            attempt_index=1,
            fallback_triggered=False,
            failed_models=[],
            latency_ms=1.0,
        )
        return draft, telemetry


class SlowStubRouter(FastStubRouter):
    """Blocks ~1s per LLM call to measure event-loop concurrency."""

    def generate_socratic_draft(
        self,
        prompt: str,
        system_instruction: str | None = None,
        start_tier: int = 0,
    ) -> tuple[NeuralSocraticDraft, ModelTelemetry]:
        time.sleep(1.0)
        return super().generate_socratic_draft(prompt, system_instruction, start_tier)


async def register_user(
    client: AsyncClient,
    email: str,
    name: str = "Budget Tester",
    *,
    expect_status: int = 201,
) -> dict[str, str]:
    """Register and return Authorization headers (or {} on non-201)."""
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123!", "full_name": name},
    )
    assert resp.status_code == expect_status, resp.text
    if expect_status != 201:
        return {}
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def post_turn(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    text: str = "help me start",
) -> Any:
    """POST /api/tutor/turn in open MATH chat mode."""
    return await client.post(
        "/api/tutor/turn",
        json={"track": "MATH", "student_input": text, "chat_mode": True},
        headers=headers,
    )
