"""Phase 1 Verification Suite: Hybrid Auth, Subject Enrollment & 4-Model Gemini Router."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from google.genai import errors
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.database import get_session
from backend.app.main import app
from backend.app.schemas.socratic import NeuralSocraticDraft
from backend.app.services.gemini_router import GeminiRouter


@pytest.fixture()
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an isolated in-memory SQLite test database and AsyncClient."""
    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    test_session_maker = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with test_session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()
    await test_engine.dispose()


async def test_local_register_login_and_me_flow(client: AsyncClient) -> None:
    """Verify Bcrypt registration, duplicate protection, JWT login, and /api/auth/me."""
    reg_resp = await client.post(
        "/api/auth/register",
        json={
            "email": "Ada.Lovelace@Example.com",
            "password": "StrongPassword123!",
            "full_name": "Ada Lovelace",
        },
    )
    assert reg_resp.status_code == 201
    reg_data = reg_resp.json()
    assert "access_token" in reg_data
    assert reg_data["user"]["email"] == "ada.lovelace@example.com"
    assert reg_data["user"]["auth_provider"] == "LOCAL"
    token = reg_data["access_token"]

    # Duplicate email registration must return 409 Conflict
    dup_resp = await client.post(
        "/api/auth/register",
        json={
            "email": "ada.lovelace@example.com",
            "password": "AnotherPassword123!",
            "full_name": "Ada Duplicate",
        },
    )
    assert dup_resp.status_code == 409

    # Login with valid credentials
    login_resp = await client.post(
        "/api/auth/login",
        json={
            "email": "ada.lovelace@example.com",
            "password": "StrongPassword123!",
        },
    )
    assert login_resp.status_code == 200
    assert "access_token" in login_resp.json()

    # Login with wrong password must return 401
    bad_login = await client.post(
        "/api/auth/login",
        json={
            "email": "ada.lovelace@example.com",
            "password": "WrongPassword!",
        },
    )
    assert bad_login.status_code == 401

    # Fetch authenticated profile via /api/auth/me
    me_resp = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["full_name"] == "Ada Lovelace"


async def test_google_oauth_mock_verification(client: AsyncClient) -> None:
    """Verify Google OAuth2 ID-token authentication and auto-provisioning."""
    mock_google_claims = {
        "email": "alan.turing@cam.ac.uk",
        "sub": "google-oauth2-sub-987654321",
        "name": "Alan Turing",
    }
    with patch(
        "backend.app.services.auth_service.google_id_token.verify_oauth2_token",
        return_value=mock_google_claims,
    ):
        resp = await client.post(
            "/api/auth/google",
            json={"id_token": "mock.google.jwt.token.value"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["user"]["email"] == "alan.turing@cam.ac.uk"
        assert body["user"]["auth_provider"] == "GOOGLE"
        assert body["access_token"]

    # Invalid Google token must return 401
    with patch(
        "backend.app.services.auth_service.google_id_token.verify_oauth2_token",
        side_effect=ValueError("Token signature invalid"),
    ):
        bad_resp = await client.post(
            "/api/auth/google",
            json={"id_token": "invalid.google.jwt.token"},
        )
        assert bad_resp.status_code == 401


async def test_subject_enrollment_and_seeded_curriculum(client: AsyncClient) -> None:
    """Verify track enrollment idempotency and default Math/Coding problem seeding."""
    reg = await client.post(
        "/api/auth/register",
        json={
            "email": "student@socratic.ai",
            "password": "Password123!",
            "full_name": "Socratic Student",
        },
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Enroll in MATH and CODE tracks (including idempotent repeat call)
    for track in ("MATH", "MATH", "CODE", "RAG"):
        enroll_resp = await client.post(
            "/api/subjects/enroll",
            json={"track": track},
            headers=headers,
        )
        assert enroll_resp.status_code == 200
        assert enroll_resp.json()["track"] == track

    list_resp = await client.get("/api/subjects/enrollments", headers=headers)
    assert list_resp.status_code == 200
    enrolled_tracks = [item["track"] for item in list_resp.json()]
    assert enrolled_tracks == ["MATH", "CODE", "RAG"]

    # Verify seeded curriculum problems
    problems_resp = await client.get("/api/subjects/problems")
    assert problems_resp.status_code == 200
    all_problems = problems_resp.json()
    assert len(all_problems) >= 4

    math_resp = await client.get("/api/subjects/problems?track=MATH")
    assert math_resp.status_code == 200
    math_problems = math_resp.json()
    assert all(p["track"] == "MATH" for p in math_problems)
    assert any(p["slug"] == "math-deriv-poly" for p in math_problems)


def test_gemini_router_429_cascade_across_all_4_models() -> None:
    """Verify simulated 429 rate-limit fallback across the 4-model Gemini cascade."""
    call_log: list[str] = []

    valid_draft_json = NeuralSocraticDraft(
        student_intent_summary="Student differentiated the first term x**3 to 3*x**2.",
        student_symbolic_claim="3*x**2",
        is_final_goal_reached_claim=False,
        socratic_question="Great job on x**3! Now what is the derivative of the 2*x term?",
    ).model_dump_json()

    class MockModelsAPI:
        def generate_content(
            self,
            *,
            model: str,
            contents: str,
            config: Any,
        ) -> Any:
            call_log.append(model)
            # Assert strict cost/grounding guardrails on every call
            assert config.response_mime_type == "application/json"
            assert config.response_schema is NeuralSocraticDraft
            assert config.tools is None
            if "flash-lite" in model:
                assert config.thinking_config is not None
                assert config.thinking_config.thinking_budget == 0

            if model in (
                "gemini-3.1-flash-lite",
                "gemini-3.5-flash-lite",
                "gemini-3.7-flash",
            ):
                raise errors.ClientError(
                    429,
                    {"error": {"message": f"Rate limit exceeded on {model}"}},
                )
            return SimpleNamespace(text=valid_draft_json, parsed=None)

    mock_client = SimpleNamespace(models=MockModelsAPI())
    router = GeminiRouter(client=mock_client)  # type: ignore[arg-type]

    draft, telemetry = router.generate_socratic_draft(
        prompt="Student input: derivative of x**3 is 3*x**2"
    )

    assert call_log == [
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-3.7-flash",
        "gemini-2.5-flash-lite",
    ]
    assert draft.student_symbolic_claim == "3*x**2"
    assert telemetry.model_used == "gemini-2.5-flash-lite"
    assert telemetry.attempt_index == 4
    assert telemetry.fallback_triggered is True
    assert telemetry.failed_models == [
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-3.7-flash",
    ]


def test_gemini_router_validation_error_fallback() -> None:
    """Verify malformed JSON on Model 1 triggers ValidationError failover to Model 2."""
    valid_draft = NeuralSocraticDraft(
        student_intent_summary="Student wrote a for loop.",
        student_symbolic_claim="for x in nums:\n    total += x",
        is_final_goal_reached_claim=False,
        socratic_question="Where is `total` initialized before the loop?",
    )

    class MockModelsValidationFallback:
        def generate_content(
            self,
            *,
            model: str,
            contents: str,
            config: Any,
        ) -> Any:
            if model == "gemini-3.1-flash-lite":
                return SimpleNamespace(text='{"broken_schema": true}', parsed=None)
            return SimpleNamespace(text=valid_draft.model_dump_json(), parsed=None)

    mock_client = SimpleNamespace(models=MockModelsValidationFallback())
    router = GeminiRouter(client=mock_client)  # type: ignore[arg-type]

    draft, telemetry = router.generate_socratic_draft(prompt="Check loop")
    assert telemetry.model_used == "gemini-3.5-flash-lite"
    assert telemetry.attempt_index == 2
    assert telemetry.failed_models == ["gemini-3.1-flash-lite"]
    assert draft.socratic_question == "Where is `total` initialized before the loop?"


def test_gemini_router_vertexai_client_initialization() -> None:
    """Verify GeminiRouter initializes google-genai Client in Vertex AI mode by default."""
    with patch("backend.app.services.gemini_router.genai.Client") as mock_client_cls:
        router = GeminiRouter(
            project="my-new-vertex-project",
            location="us-central1",
            use_vertexai=True,
        )
        _ = router.client
        mock_client_cls.assert_called_once_with(
            vertexai=True,
            project="my-new-vertex-project",
            location="us-central1",
        )

