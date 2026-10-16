"""Phase 3 Verification Suite: Grounded RAG Engine & LangGraph Socratic State Machine."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from httpx import ASGITransport, AsyncClient
import pymupdf as fitz
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.database import get_session
from backend.app.graph.workflow import execute_socratic_turn
from backend.app.main import app
from backend.app.schemas.socratic import ModelTelemetry, NeuralSocraticDraft
from backend.app.services.gemini_router import get_gemini_router
from backend.app.symbolic.rag_verifier import verify_rag_turn

MATH_PROBLEM_PAYLOAD = {
    "id": 1,
    "slug": "math-deriv-poly",
    "title": "Power Rule Derivative of a Cubic Polynomial",
    "prompt": "Find f'(x) for f(x) = x**3 + 2*x.",
    "symbolic_rules_json": {
        "variables": ["x"],
        "target_expr": "3*x**2 + 2",
        "allowed_intermediate_exprs": ["3*x**2", "2", "x**3", "2*x"],
        "fallback_question": (
            "Apply the power rule d/dx[x^n] = n*x^(n-1) to each term of "
            "x**3 + 2*x separately. What is the derivative of the first term x**3?"
        ),
    },
}


class ScriptedMockRouter:
    """Deterministic mock GeminiRouter for testing multi-step LangGraph loops."""

    def __init__(self, drafts: list[NeuralSocraticDraft]) -> None:
        self.drafts = drafts
        self.prompts_received: list[str] = []
        self.tiers_requested: list[int] = []
        self.embedding_dim = 768

    def generate_socratic_draft(
        self,
        prompt: str,
        system_instruction: str | None = None,
        start_tier: int = 0,
    ) -> tuple[NeuralSocraticDraft, ModelTelemetry]:
        _ = system_instruction
        call_idx = len(self.prompts_received)
        self.prompts_received.append(prompt)
        self.tiers_requested.append(start_tier)
        selected_draft = self.drafts[min(call_idx, len(self.drafts) - 1)]
        models = [
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash-lite",
            "gemini-3.7-flash",
            "gemini-2.5-flash-lite",
        ]
        model_used = models[min(start_tier, len(models) - 1)]
        telemetry = ModelTelemetry(
            model_used=model_used,
            attempt_index=1,
            fallback_triggered=False,
            failed_models=[],
            latency_ms=12.5,
        )
        return selected_draft, telemetry

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return deterministic normalized 768-dim unit vectors."""
        return [[1.0] + [0.0] * 767 for _ in texts]


async def test_langgraph_leak_on_attempt_1_self_corrects_on_attempt_2() -> None:
    """Verify Attempt 1 math leak is rejected by Step 2, routed to Step 3, and passes on Attempt 2."""
    leaked_attempt_1 = NeuralSocraticDraft(
        student_intent_summary="Student differentiated x**3 to 3*x**2.",
        student_symbolic_claim="3*x**2",
        is_final_goal_reached_claim=False,
        socratic_question="Good start! Now add 2 so the final answer is 3*x**2 + 2.",
    )
    clean_attempt_2 = NeuralSocraticDraft(
        student_intent_summary="Student differentiated x**3 to 3*x**2.",
        student_symbolic_claim="3*x**2",
        is_final_goal_reached_claim=False,
        socratic_question="You nailed x**3! Now what rule gives the derivative of 2*x?",
    )

    mock_router = ScriptedMockRouter([leaked_attempt_1, clean_attempt_2])
    response = await execute_socratic_turn(
        session_id="test-session-self-correct",
        track="MATH",
        student_input="The derivative of x**3 is 3*x**2",
        problem_payload=MATH_PROBLEM_PAYLOAD,
        router=mock_router,  # type: ignore[arg-type]
    )

    assert response.iterations_taken == 2
    assert response.circuit_breaker_triggered is False
    assert response.problem_solved is False
    assert len(response.audit_trail) == 2

    assert response.audit_trail[0].iteration == 1
    assert response.audit_trail[0].passed is False
    assert response.audit_trail[0].answer_leaked_in_hint is True
    assert response.audit_trail[0].model_used == "gemini-3.1-flash-lite"

    assert "SYMBOLIC CRITIQUE FROM PREVIOUS ATTEMPT" in mock_router.prompts_received[1]
    assert "LEAK VIOLATION" in mock_router.prompts_received[1]

    assert response.audit_trail[1].iteration == 2
    assert response.audit_trail[1].passed is True
    assert response.audit_trail[1].answer_leaked_in_hint is False
    assert response.audit_trail[1].model_used == "gemini-3.5-flash-lite"
    assert response.socratic_reply == clean_attempt_2.socratic_question


async def test_langgraph_3_failures_trigger_circuit_breaker() -> None:
    """Verify 3 consecutive symbolic failures trigger circuit_breaker_node at iteration == 3."""
    persistent_leak = NeuralSocraticDraft(
        student_intent_summary="Student is stuck.",
        student_symbolic_claim="x**3",
        is_final_goal_reached_claim=False,
        socratic_question="The answer is simply 3*x**2 + 2.",
    )
    mock_router = ScriptedMockRouter([persistent_leak] * 3)

    response = await execute_socratic_turn(
        session_id="test-session-circuit-breaker",
        track="MATH",
        student_input="I am not sure how to start",
        problem_payload=MATH_PROBLEM_PAYLOAD,
        router=mock_router,  # type: ignore[arg-type]
    )

    assert len(mock_router.prompts_received) == 3
    assert response.iterations_taken == 3
    assert response.circuit_breaker_triggered is True
    assert response.problem_solved is False
    assert len(response.audit_trail) == 3
    assert all(v.passed is False for v in response.audit_trail)
    assert (
        response.socratic_reply
        == MATH_PROBLEM_PAYLOAD["symbolic_rules_json"]["fallback_question"]
    )


def test_rag_verifier_rejects_hallucinated_quote_and_low_similarity() -> None:
    """Verify rag_verifier rejects paraphrased/hallucinated quotes and similarity < 0.65."""
    chunks: list[dict[str, Any]] = [
        {
            "id": 101,
            "chapter_id": 1,
            "chunk_index": 0,
            "page_number": 1,
            "content": (
                "Backpropagation computes the gradient of the loss function with "
                "respect to the weights of the neural network using the chain rule."
            ),
            "similarity": 0.89,
        }
    ]
    rules = {"target_concept": "chain rule"}

    hallucinated_draft = NeuralSocraticDraft(
        student_intent_summary="Student asked how weights are updated.",
        student_symbolic_claim="weights update",
        is_final_goal_reached_claim=False,
        cited_chunk_id=101,
        verbatim_quote="Backpropagation calculates derivatives for every layer automatically.",
        socratic_question="Which calculus rule links composite functions across layers?",
    )
    verdict_bad, solved_bad = verify_rag_turn(
        draft=hallucinated_draft, retrieved_chunks=chunks, problem_rules=rules
    )
    assert verdict_bad.passed is False
    assert solved_bad is False
    assert (
        verdict_bad.rejection_reason
        == "CITATION VIOLATION: verbatim_quote must be an exact character-for-character substring of the retrieved chunk."
    )

    valid_rag_draft = NeuralSocraticDraft(
        student_intent_summary="Student is exploring gradient calculation.",
        student_symbolic_claim="gradient of the loss",
        is_final_goal_reached_claim=False,
        cited_chunk_id=101,
        verbatim_quote="gradient of the loss function with respect to the weights",
        socratic_question="How does calculus allow us to differentiate nested composite functions?",
    )
    verdict_ok, _ = verify_rag_turn(
        draft=valid_rag_draft, retrieved_chunks=chunks, problem_rules=rules
    )
    assert verdict_ok.passed is True
    assert verdict_ok.rejection_reason is None

    low_sim_chunks = [{**chunks[0], "similarity": 0.42}]
    verdict_oos, _ = verify_rag_turn(
        draft=valid_rag_draft, retrieved_chunks=low_sim_chunks, problem_rules=rules
    )
    assert verdict_oos.passed is False
    assert "OUT_OF_SCOPE VIOLATION" in (verdict_oos.rejection_reason or "")


async def test_rag_upload_and_tutor_turn_endpoints() -> None:
    """Verify /api/rag/upload, /api/rag/chapters, /api/tutor/turn, and /api/tutor/session/{id}/history."""
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

    clean_draft = NeuralSocraticDraft(
        student_intent_summary="Student differentiated x**3 to 3*x**2.",
        student_symbolic_claim="3*x**2",
        is_final_goal_reached_claim=False,
        socratic_question="Great! Now what is the derivative of 2*x?",
    )
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_gemini_router] = lambda: ScriptedMockRouter([clean_draft])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        reg = await client.post(
            "/api/auth/register",
            json={
                "email": "rag_student@socratic.ai",
                "password": "Password123!",
                "full_name": "RAG Tester",
            },
        )
        headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}

        doc = fitz.open()
        doc.new_page().insert_text(
            (50, 50),
            "Photosynthesis converts light energy into chemical energy stored in glucose.",
        )
        pdf_bytes = doc.tobytes()
        doc.close()

        upload_resp = await client.post(
            "/api/rag/upload",
            files={"file": ("biology_ch1.pdf", pdf_bytes, "application/pdf")},
            data={"title": "Cellular Energetics", "target_concept": "glucose"},
            headers=headers,
        )
        assert upload_resp.status_code == 201
        assert upload_resp.json()["embedding_dimensions"] == 768

        chapters_resp = await client.get("/api/rag/chapters", headers=headers)
        assert chapters_resp.status_code == 200
        assert len(chapters_resp.json()) == 1

        turn_resp = await client.post(
            "/api/tutor/turn",
            json={"track": "MATH", "student_input": "3*x**2"},
            headers=headers,
        )
        assert turn_resp.status_code == 200
        turn_data = turn_resp.json()
        assert turn_data["iterations_taken"] == 1

        hist_resp = await client.get(
            f"/api/tutor/session/{turn_data['session_id']}/history",
            headers=headers,
        )
        assert hist_resp.status_code == 200
        assert len(hist_resp.json()["turns"]) == 1

    app.dependency_overrides.clear()
    await test_engine.dispose()
