"""Open-chat RAG anti-leak and circuit-breaker fallback tests."""

from __future__ import annotations

from typing import Any

from backend.app.graph.workflow import execute_socratic_turn
from backend.app.schemas.socratic import ModelTelemetry, NeuralSocraticDraft
from backend.app.symbolic.rag_verifier import verify_rag_turn


class _ScriptedRouter:
    """Minimal draft router for circuit-breaker anti-leak checks."""

    def __init__(self, drafts: list[NeuralSocraticDraft]) -> None:
        self.drafts = drafts
        self.prompts_received: list[str] = []

    def generate_socratic_draft(
        self,
        prompt: str,
        system_instruction: str | None = None,
        start_tier: int = 0,
    ) -> tuple[NeuralSocraticDraft, ModelTelemetry]:
        _ = (system_instruction, start_tier)
        idx = len(self.prompts_received)
        self.prompts_received.append(prompt)
        draft = self.drafts[min(idx, len(self.drafts) - 1)]
        return draft, ModelTelemetry(
            model_used="gemini-3.1-flash-lite",
            attempt_index=1,
            fallback_triggered=False,
            failed_models=[],
            latency_ms=1.0,
        )

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * 767 for _ in texts]


def test_rag_open_chat_rejects_textbook_dump_but_allows_guiding_question() -> None:
    """Open-chat RAG (no target_concept) rejects pasted chunk text, allows own-words hints."""
    passage = (
        "are “animal factories” that produce more cattle, sheep, and pigs. "
        "Chickens lay eggs, and cows, sheep, THE REIGN OF THE FARMER "
        "describes how agriculture reshaped human settlement patterns."
    )
    chunks: list[dict[str, Any]] = [
        {
            "id": 202,
            "chapter_id": 2,
            "chunk_index": 0,
            "page_number": 19,
            "content": passage,
            "similarity": 0.91,
        }
    ]
    quote = "are “animal factories” that produce more cattle, sheep, and pigs"
    dumped = NeuralSocraticDraft(
        student_intent_summary="Student asked what Reign of the Farmer means.",
        student_symbolic_claim="NONE",
        is_final_goal_reached_claim=False,
        cited_chunk_id=202,
        verbatim_quote=quote,
        socratic_question=(
            f'Based on the uploaded textbook passage ("{passage[:180]}..."), '
            "how would you summarize the key mechanism in your own words?"
        ),
    )
    verdict_dump, _ = verify_rag_turn(
        draft=dumped, retrieved_chunks=chunks, problem_rules={"chat_mode": True}
    )
    assert verdict_dump.passed is False
    assert verdict_dump.answer_leaked_in_hint is True
    assert "Textbook Dump" in (verdict_dump.symbolic_rule_checked or "")

    clean = NeuralSocraticDraft(
        student_intent_summary="Student asked what Reign of the Farmer means.",
        student_symbolic_claim="NONE",
        is_final_goal_reached_claim=False,
        cited_chunk_id=202,
        verbatim_quote=quote,
        socratic_question=(
            "Interesting question. Before we dig in, what comes to mind when you "
            "hear the word 'reign' in an agricultural context?"
        ),
    )
    verdict_clean, _ = verify_rag_turn(
        draft=clean, retrieved_chunks=chunks, problem_rules={"chat_mode": True}
    )
    assert verdict_clean.passed is True
    assert verdict_clean.answer_leaked_in_hint is False


async def test_rag_circuit_breaker_does_not_paste_textbook_snippet() -> None:
    """After 3 RAG leak failures, fallback must not dump retrieved chunk text."""
    passage = (
        "are “animal factories” that produce more cattle, sheep, and pigs. "
        "Chickens lay eggs, and cows, sheep, THE REIGN OF THE FARMER 19."
    )
    chunks = [
        {
            "id": 303,
            "content": passage,
            "similarity": 0.88,
            "page_number": 19,
        }
    ]
    dumped = NeuralSocraticDraft(
        student_intent_summary="Student asked about reign of farmer.",
        student_symbolic_claim="NONE",
        is_final_goal_reached_claim=False,
        cited_chunk_id=303,
        verbatim_quote="are “animal factories” that produce more cattle",
        socratic_question=(
            f'Based on the uploaded textbook passage ("{passage}"), '
            "how would you summarize the key mechanism?"
        ),
    )
    mock_router = _ScriptedRouter([dumped] * 3)
    response = await execute_socratic_turn(
        session_id="test-rag-circuit-breaker-no-leak",
        track="RAG",
        student_input="what is the meaning of reign of farmer",
        problem_payload={
            "title": "Uploaded Chapter",
            "prompt": "Socratic chat grounded in uploaded PDF.",
            "symbolic_rules_json": {"chat_mode": True, "target_concept": ""},
        },
        retrieved_chunks=chunks,
        router=mock_router,  # type: ignore[arg-type]
    )
    assert response.circuit_breaker_triggered is True
    assert "animal factories" not in response.socratic_reply.lower()
    assert "REIGN OF THE FARMER" not in response.socratic_reply
    assert "CRITICAL ANTI-LEAK" in mock_router.prompts_received[0]
