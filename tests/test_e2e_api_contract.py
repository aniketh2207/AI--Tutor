"""Phase 4 Verification Suite: OpenAPI Schema Alignment & End-to-End User Flow."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.database import get_session
from backend.app.main import app
from backend.app.schemas.socratic import ModelTelemetry, NeuralSocraticDraft
from backend.app.services.gemini_router import get_gemini_router

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_TYPES_PATH = REPO_ROOT / "frontend" / "src" / "types" / "api.ts"


class E2EMockRouter:
    """Mock router returning a leak on Attempt 1 and a valid hint on Attempt 2."""

    def __init__(self) -> None:
        self.calls = 0
        self.embedding_dim = 768

    def generate_socratic_draft(
        self,
        prompt: str,
        system_instruction: str | None = None,
        start_tier: int = 0,
    ) -> tuple[NeuralSocraticDraft, ModelTelemetry]:
        _ = (prompt, system_instruction)
        self.calls += 1
        if self.calls == 1:
            draft = NeuralSocraticDraft(
                student_intent_summary="Student differentiated x**3 to 3*x**2.",
                student_symbolic_claim="3*x**2",
                is_final_goal_reached_claim=False,
                socratic_question="Almost there! The final answer is 3*x**2 + 2.",
            )
            model_name = "gemini-3.1-flash-lite"
        else:
            draft = NeuralSocraticDraft(
                student_intent_summary="Student differentiated x**3 to 3*x**2.",
                student_symbolic_claim="3*x**2",
                is_final_goal_reached_claim=False,
                socratic_question=(
                    "You found the derivative of x**3. Now what is the derivative "
                    "of the linear term 2*x?"
                ),
            )
            model_name = (
                "gemini-3.5-flash-lite"
                if start_tier >= 1
                else "gemini-3.1-flash-lite"
            )
        telemetry = ModelTelemetry(
            model_used=model_name,
            attempt_index=1,
            fallback_triggered=False,
            failed_models=[],
            latency_ms=18.4,
        )
        return draft, telemetry

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * 767 for _ in texts]


def test_openapi_schema_and_frontend_typescript_contract_alignment() -> None:
    """Verify FastAPI OpenAPI schema paths/components match frontend/src/types/api.ts."""
    openapi_schema = app.openapi()
    paths = openapi_schema.get("paths", {})

    required_endpoints = [
        "/health",
        "/livez",
        "/api/auth/register",
        "/api/auth/login",
        "/api/auth/google",
        "/api/auth/public-config",
        "/api/auth/me",
        "/api/subjects/enroll",
        "/api/subjects/enrollments",
        "/api/subjects/problems",
        "/api/tutor/turn",
        "/api/tutor/session/{session_id}/history",
        "/api/rag/upload",
        "/api/rag/chapters",
    ]
    for endpoint in required_endpoints:
        assert endpoint in paths, f"Missing OpenAPI endpoint: {endpoint}"

    schemas = openapi_schema.get("components", {}).get("schemas", {})
    assert "SocraticTurnResponse" in schemas
    assert "SymbolicVerdict" in schemas
    assert "AuthTokenResponse" in schemas

    turn_props = set(schemas["SocraticTurnResponse"]["properties"].keys())
    assert turn_props == {
        "session_id",
        "track",
        "socratic_reply",
        "problem_solved",
        "iterations_taken",
        "circuit_breaker_triggered",
        "audit_trail",
    }

    verdict_props = set(schemas["SymbolicVerdict"]["properties"].keys())
    assert verdict_props == {
        "iteration",
        "passed",
        "student_step_correct",
        "answer_leaked_in_hint",
        "rejection_reason",
        "symbolic_rule_checked",
        "model_used",
        "latency_ms",
    }

    # Verify frontend/src/types/api.ts defines matching interfaces and fields
    assert FRONTEND_TYPES_PATH.exists(), "frontend/src/types/api.ts must exist"
    ts_content = FRONTEND_TYPES_PATH.read_text(encoding="utf-8")
    for required_ts_symbol in [
        "interface NeuralSocraticDraft",
        "interface SymbolicVerdict",
        "interface SocraticTurnResponse",
        "interface AuthTokenResponse",
        "interface EnrollmentResponse",
        "interface ProblemItemResponse",
        "interface RagUploadResponse",
        "answer_leaked_in_hint: boolean",
        "circuit_breaker_triggered: boolean",
        "audit_trail: SymbolicVerdict[]",
    ]:
        assert required_ts_symbol in ts_content, (
            f"Missing TypeScript contract definition '{required_ts_symbol}' in api.ts"
        )


async def test_full_e2e_user_flow_register_enroll_turn_and_audit_trail() -> None:
    """Verify full E2E user journey: Register -> Enroll -> Submit Turn -> Verify Audit Trail JSON."""
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

    mock_router = E2EMockRouter()
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_gemini_router] = lambda: mock_router

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # Step 1: Register new student
        reg_resp = await client.post(
            "/api/auth/register",
            json={
                "email": "e2e_architect@socratic.ai",
                "password": "ArchitectPassword123!",
                "full_name": "E2E Architect",
            },
        )
        assert reg_resp.status_code == 201
        token = reg_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Step 2: Enroll in Track 1 (MATH)
        enroll_resp = await client.post(
            "/api/subjects/enroll",
            json={"track": "MATH"},
            headers=headers,
        )
        assert enroll_resp.status_code == 200
        assert enroll_resp.json()["track"] == "MATH"

        # Step 3: Fetch seeded MATH problems
        probs_resp = await client.get("/api/subjects/problems?track=MATH")
        assert probs_resp.status_code == 200
        math_problem_id = probs_resp.json()[0]["id"]

        # Step 4: Submit Socratic turn (Attempt 1 leaks -> Step 2 rejects -> Attempt 2 passes)
        turn_resp = await client.post(
            "/api/tutor/turn",
            json={
                "track": "MATH",
                "problem_id": math_problem_id,
                "student_input": "3*x**2",
            },
            headers=headers,
        )
        assert turn_resp.status_code == 200
        turn_json = turn_resp.json()

        assert turn_json["track"] == "MATH"
        assert turn_json["problem_solved"] is False
        assert turn_json["iterations_taken"] == 2
        assert turn_json["circuit_breaker_triggered"] is False
        assert len(turn_json["audit_trail"]) == 2

        # Inspect Iteration 1 (Rejected leak) & Iteration 2 (Certified output)
        iter_1 = turn_json["audit_trail"][0]
        iter_2 = turn_json["audit_trail"][1]
        assert iter_1["passed"] is False
        assert iter_1["answer_leaked_in_hint"] is True
        assert "LEAK VIOLATION" in iter_1["rejection_reason"]

        assert iter_2["passed"] is True
        assert iter_2["answer_leaked_in_hint"] is False
        assert iter_2["model_used"] == "gemini-3.5-flash-lite"

        # Step 5: Verify persisted session audit history
        hist_resp = await client.get(
            f"/api/tutor/session/{turn_json['session_id']}/history",
            headers=headers,
        )
        assert hist_resp.status_code == 200
        hist_json = hist_resp.json()
        assert hist_json["session_id"] == turn_json["session_id"]
        assert len(hist_json["turns"]) == 1
        assert len(hist_json["turns"][0]["audit_trail"]) == 2

        # Step 6: Freeform open chat (no problem_id) — student asks their own question
        mock_router.calls = 0
        chat_resp = await client.post(
            "/api/tutor/turn",
            json={
                "track": "MATH",
                "chat_mode": True,
                "student_input": (
                    "How do I start differentiating f(x) = x**3 + 2*x?"
                ),
            },
            headers=headers,
        )
        assert chat_resp.status_code == 200
        chat_json = chat_resp.json()
        assert chat_json["track"] == "MATH"
        assert chat_json["socratic_reply"]
        assert len(chat_json["audit_trail"]) >= 1

    app.dependency_overrides.clear()
    await test_engine.dispose()


def test_phase_5_docker_cicd_and_readme_readiness() -> None:
    """Verify Phase 5 Dockerfile, docker-compose.yml, CI/CD workflow, and README.md."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.11-slim AS builder" in dockerfile
    assert "FROM python:3.11-slim AS runtime" in dockerfile
    assert "USER appuser" in dockerfile
    assert "uvicorn backend.app.main:app" in dockerfile

    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "pgvector/pgvector:pg16" in compose
    assert "socratic-backend" in compose
    assert "socratic-frontend" in compose

    cicd = (REPO_ROOT / ".github" / "workflows" / "ci_cd.yml").read_text(
        encoding="utf-8"
    )
    assert "pytest -v" in cicd
    assert "--min-instances=0" in cicd
    assert "--max-instances=2" in cicd
    assert "--memory=512Mi" in cicd
    assert "--set-secrets=" in cicd

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "4-Step Socratic Loop" in readme
    assert "Continue with Google" in readme
    assert "GOOGLE_CLIENT_ID" in readme
    assert "Deploy and roll back" in readme

