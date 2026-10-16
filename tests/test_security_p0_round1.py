"""Round 1 P0 security tests (TDD): ownership, sandbox flag, prod secrets, Google errors."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.config import Settings, get_settings
from backend.app.database import get_session
from backend.app.main import app
from backend.app.schemas.socratic import ModelTelemetry, NeuralSocraticDraft
from backend.app.services.gemini_router import get_gemini_router
from backend.app.symbolic.ast_verifier import verify_code_turn


class StubEmbedRouter:
    """Minimal router for PDF upload embedding during ownership tests."""

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
            student_intent_summary="Student asked about the chapter.",
            student_symbolic_claim="NONE",
            is_final_goal_reached_claim=False,
            cited_chunk_id=1,
            verbatim_quote="secret chapter content for user A only",
            socratic_question="What does the passage say about the key idea?",
        )
        telemetry = ModelTelemetry(
            model_used="gemini-3.1-flash-lite",
            attempt_index=1,
            fallback_triggered=False,
            failed_models=[],
            latency_ms=1.0,
        )
        return draft, telemetry


@pytest.fixture()
async def ownership_client() -> AsyncGenerator[AsyncClient, None]:
    """Isolated DB + stub Gemini for chapter ownership API tests."""
    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
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
    app.dependency_overrides[get_gemini_router] = lambda: StubEmbedRouter()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client

    app.dependency_overrides.clear()
    await test_engine.dispose()


async def _register(
    client: AsyncClient, email: str, name: str
) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "Password123!",
            "full_name": name,
        },
    )
    assert resp.status_code == 201
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_user_b_cannot_fetch_user_a_chapter_chunks(
    ownership_client: AsyncClient,
) -> None:
    """User B requesting User A's chapter by ID must get 404 (not 200 with content)."""
    headers_a = await _register(ownership_client, "owner_a@test.com", "User A")
    headers_b = await _register(ownership_client, "intruder_b@test.com", "User B")

    import pymupdf as fitz

    doc = fitz.open()
    doc.new_page().insert_text((40, 40), "secret chapter content for user A only")
    pdf_bytes = doc.tobytes()
    doc.close()

    upload = await ownership_client.post(
        "/api/rag/upload",
        files={"file": ("a_secret.pdf", pdf_bytes, "application/pdf")},
        data={"title": "User A Secret Notes"},
        headers=headers_a,
    )
    assert upload.status_code == 201
    chapter_id = upload.json()["chapter"]["id"]

    # User B must not list User A's chapter
    list_b = await ownership_client.get("/api/rag/chapters", headers=headers_b)
    assert list_b.status_code == 200
    assert all(ch["id"] != chapter_id for ch in list_b.json())

    # User B must not read chunks by ID
    chunks_b = await ownership_client.get(
        f"/api/rag/chapters/{chapter_id}/chunks",
        headers=headers_b,
    )
    assert chunks_b.status_code == 404


async def test_user_b_turn_without_chapter_id_does_not_use_user_a_chapter(
    ownership_client: AsyncClient,
) -> None:
    """Omitting chapter_id must not silently bind to another student's chapter."""
    import pymupdf as fitz

    headers_a = await _register(ownership_client, "owner2_a@test.com", "User A2")
    headers_b = await _register(ownership_client, "intruder2_b@test.com", "User B2")

    doc = fitz.open()
    doc.new_page().insert_text((40, 40), "secret chapter content for user A only")
    pdf_bytes = doc.tobytes()
    doc.close()

    upload = await ownership_client.post(
        "/api/rag/upload",
        files={"file": ("a_only.pdf", pdf_bytes, "application/pdf")},
        data={"title": "A Private Textbook"},
        headers=headers_a,
    )
    assert upload.status_code == 201
    chapter_a_id = upload.json()["chapter"]["id"]

    # Explicit steal attempt
    steal = await ownership_client.post(
        "/api/tutor/turn",
        json={
            "track": "RAG",
            "chapter_id": chapter_a_id,
            "student_input": "Summarize the secret notes",
            "chat_mode": True,
        },
        headers=headers_b,
    )
    assert steal.status_code == 404

    # No chapter_id: must 404 (User B has no chapters), not return User A's grounding
    no_id = await ownership_client.post(
        "/api/tutor/turn",
        json={
            "track": "RAG",
            "student_input": "Summarize the secret notes",
            "chat_mode": True,
        },
        headers=headers_b,
    )
    assert no_id.status_code == 404
    detail = str(no_id.json().get("detail", "")).lower()
    assert "secret" not in detail


def test_code_execution_disabled_by_default_and_skips_sandbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ENABLE_CODE_EXECUTION defaults false; sandbox subprocess must not run."""
    monkeypatch.delenv("ENABLE_CODE_EXECUTION", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.enable_code_execution is False

    valid_code = (
        "def sum_elements(nums):\n"
        "    total = 0\n"
        "    for x in nums:\n"
        "        total += x\n"
        "    return total\n"
    )
    draft = NeuralSocraticDraft(
        student_intent_summary="Valid iterative sum.",
        student_symbolic_claim=valid_code,
        is_final_goal_reached_claim=False,
        socratic_question="Nice structural approach — keep going.",
    )
    rules = {
        "function_name": "sum_elements",
        "required_ast_nodes": ["FunctionDef", "For", "Return"],
        "forbidden_ast_nodes": ["While"],
        "forbidden_calls": ["sum"],
        "test_cases": [{"input": [[1, 2, 3]], "expected": 6}],
        "chat_mode": False,
    }

    with patch(
        "backend.app.symbolic.ast_verifier.run_code_in_sandbox",
        side_effect=AssertionError("sandbox must not run when execution disabled"),
    ) as sandbox_mock:
        verdict, solved = verify_code_turn(
            draft=draft,
            problem_rules=rules,
            student_raw_input=valid_code,
        )
        sandbox_mock.assert_not_called()

    assert verdict.passed is True
    assert "EXECUTION_DISABLED" in verdict.symbolic_rule_checked
    # AST-only mode: required nodes + no forbidden calls counts as structurally solved
    assert solved is True
    assert verdict.student_step_correct is True


def test_production_startup_rejects_default_jwt_secret() -> None:
    """APP_ENV=production with the hardcoded default JWT secret must raise."""
    from backend.app.startup_validation import validate_production_settings

    insecure = Settings(
        app_env="production",
        debug=False,
        jwt_secret_key="socratic-tutor-dev-secret-key-change-in-prod-32b",
        google_client_id="123456789-real.apps.googleusercontent.com",
    )
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        validate_production_settings(insecure)

    insecure_debug = Settings(
        app_env="production",
        debug=True,
        jwt_secret_key="a-sufficiently-long-production-secret-key-32b+",
        google_client_id="123456789-real.apps.googleusercontent.com",
    )
    with pytest.raises(RuntimeError, match="DEBUG"):
        validate_production_settings(insecure_debug)


async def test_public_auth_config_exposes_google_client_flag(
    ownership_client: AsyncClient,
) -> None:
    """Frontend needs /api/auth/public-config to render Continue with Google."""
    resp = await ownership_client.get("/api/auth/public-config")
    assert resp.status_code == 200
    data = resp.json()
    assert "google_client_id" in data
    assert "google_sign_in_enabled" in data
    assert isinstance(data["google_sign_in_enabled"], bool)


async def test_google_auth_error_is_generic(ownership_client: AsyncClient) -> None:
    """Failed Google verification must not leak exception strings to the client."""
    with patch(
        "backend.app.services.auth_service.google_id_token.verify_oauth2_token",
        side_effect=ValueError("Token used too early, 12345 clock skew detail"),
    ):
        resp = await ownership_client.post(
            "/api/auth/google",
            json={"id_token": "invalid.google.jwt.token"},
        )
    assert resp.status_code == 401
    detail = resp.json()["detail"]
    assert detail == "Google sign-in failed."
    assert "clock skew" not in detail.lower()
    assert "12345" not in detail
