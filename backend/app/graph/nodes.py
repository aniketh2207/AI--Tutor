"""LangGraph nodes for the 4-Step Neuro-Symbolic Socratic Cycle (`document.md` Section 6)."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from backend.app.config import get_settings
from backend.app.graph.state import SocraticGraphState
from backend.app.schemas.socratic import NeuralSocraticDraft
from backend.app.services.gemini_router import GeminiRouter, get_gemini_router
from backend.app.symbolic.ast_verifier import verify_code_turn
from backend.app.symbolic.math_verifier import verify_math_turn
from backend.app.symbolic.rag_verifier import verify_rag_turn


def build_socratic_prompt(state: SocraticGraphState) -> str:
    """Assemble the context-rich prompt for Step 1 (Intuitive Leap) & Step 3 (Self-Correction)."""
    track = state["track"]
    payload = state.get("problem_payload") or {}
    student_input = state.get("student_input", "")
    iteration = state.get("iteration", 0)
    audit_trail = state.get("audit_trail") or []
    history = state.get("conversation_history") or []
    rules = payload.get("symbolic_rules_json") or {}
    chat_mode = bool(rules.get("chat_mode", False))

    sections: list[str] = [
        "ROLE: You are a warm, conversational Socratic study tutor in a chat interface.",
        "Reply like a helpful chat partner: ask guiding questions, acknowledge the student's "
        "words, and never dump the final answer. Keep `socratic_question` natural and chatty "
        "(2-5 sentences max), not a yes/no quiz form.",
        f"TRACK: {track}",
        f"MODE: {'OPEN_CHAT (student asks freely)' if chat_mode else 'PRACTICE_PROBLEM'}",
        f"CONTEXT TITLE: {payload.get('title', 'Open Socratic Chat')}",
        f"CONTEXT PROMPT: {payload.get('prompt', '')}",
    ]

    if history:
        history_lines = []
        for item in history[-8:]:
            role = str(item.get("role", "student")).upper()
            content = str(item.get("content", "")).strip()
            if content:
                history_lines.append(f"{role}: {content}")
        if history_lines:
            sections.append(
                "PRIOR CHAT (for continuity — respond to the latest student message):\n"
                + "\n".join(history_lines)
            )

    if track == "MATH":
        sections.append(
            "SYMBOLIC MATH INSTRUCTIONS: If the student wrote a math expression, put it in "
            "`student_symbolic_claim` using valid SymPy syntax (e.g. '3*x**2'). "
            "If they only asked a natural-language question, set `student_symbolic_claim` to "
            "'NONE' and coach them with Socratic questions. "
            "Never state the final closed-form answer."
        )
    elif track == "CODE":
        sections.append(
            "SYMBOLIC CODE INSTRUCTIONS: If the student pasted Python code, copy it into "
            "`student_symbolic_claim`. If they asked a conceptual coding question, set "
            "`student_symbolic_claim` to 'NONE' and guide with questions. "
            "Never include markdown code blocks (```python) or full `def ...` solutions "
            "inside `socratic_question`."
        )
    elif track == "RAG":
        chunks = state.get("retrieved_chunks") or []
        chunks_formatted = json.dumps(
            [
                {
                    "chunk_id": c.get("id"),
                    "page_number": c.get("page_number"),
                    "similarity": c.get("similarity"),
                    "content": c.get("content"),
                }
                for c in chunks[:3]
            ],
            indent=2,
        )
        sections.append(
            "GROUNDED RAG INSTRUCTIONS:\n"
            "1. Set `cited_chunk_id` to one retrieved chunk id below.\n"
            "2. Copy an exact 100% character-for-character substring from that chunk "
            "into `verbatim_quote` ONLY (for citation verification).\n"
            "3. CRITICAL ANTI-LEAK: `socratic_question` must be a short guiding question "
            "in YOUR OWN WORDS. Do NOT paste, quote, or closely restate textbook "
            "sentences, page titles, or long phrases from the chunks inside "
            "`socratic_question`. The system attaches the citation separately.\n"
            "4. Never answer the student's question directly from the passage; ask what "
            "they notice or how they would define the idea.\n"
            f"RETRIEVED TEXTBOOK CHUNKS:\n{chunks_formatted}"
        )

    sections.append(f"LATEST STUDENT MESSAGE:\n{student_input}")

    # Step 3 — Correction & Alignment: inject structured symbolic critique on retry
    if iteration > 0 and audit_trail:
        last_verdict = audit_trail[-1]
        rejection_reason = last_verdict.get("rejection_reason") or "Rule violation."
        rule_checked = last_verdict.get("symbolic_rule_checked") or "Symbolic Verifier"
        leak_fix = ""
        if "LEAK VIOLATION" in rejection_reason or "Anti-Leak" in rule_checked:
            leak_fix = (
                "\nFIX REQUIRED: Keep `verbatim_quote` for citation, but rewrite "
                "`socratic_question` as a brief question with ZERO textbook wording "
                "(no quoted passage, no page headers, no copied clauses)."
            )
        sections.append(
            "=== SYMBOLIC CRITIQUE FROM PREVIOUS ATTEMPT (MUST SELF-CORRECT) ===\n"
            f"Rule '{rule_checked}' violated: {rejection_reason}\n"
            "Regenerate your JSON response strictly resolving this symbolic violation."
            f"{leak_fix}"
        )

    return "\n\n".join(sections)


def ground_truth_node(state: SocraticGraphState) -> dict[str, Any]:
    """Step 0: Initialize Socratic cycle counters and ground-truth state."""
    return {
        "iteration": 0,
        "audit_trail": [],
        "latest_draft": None,
        "final_reply": "",
        "problem_solved": False,
        "circuit_breaker_triggered": False,
        "problem_payload": state.get("problem_payload") or {},
        "retrieved_chunks": state.get("retrieved_chunks") or [],
    }


async def neural_leap_node(
    state: SocraticGraphState,
    router: GeminiRouter | None = None,
) -> dict[str, Any]:
    """Step 1 (Intuitive Leap) & Step 3 (Retry): Generate structured Socratic draft via Gemini."""
    active_router = router or get_gemini_router()
    iteration = state.get("iteration", 0)
    prompt = build_socratic_prompt(state)

    # Offload blocking Vertex/Gemini I/O so concurrent /turn requests can overlap.
    draft, telemetry = await asyncio.to_thread(
        active_router.generate_socratic_draft,
        prompt,
        None,
        iteration,
    )
    return {
        "latest_draft": {
            "draft": draft.model_dump(),
            "telemetry": telemetry.model_dump(),
        }
    }


def symbolic_interrogation_node(state: SocraticGraphState) -> dict[str, Any]:
    """Step 2 (Socratic Interrogation): Deterministic SymPy, AST, or RAG verification."""
    settings = get_settings()
    track = state["track"]
    next_iteration = state.get("iteration", 0) + 1
    latest_bundle = state.get("latest_draft") or {}
    draft_dict = latest_bundle.get("draft") or {}
    telemetry_dict = latest_bundle.get("telemetry") or {}

    draft = NeuralSocraticDraft.model_validate(draft_dict)
    model_used = str(
        telemetry_dict.get("model_used") or settings.gemini_primary_model
    )
    rules = (state.get("problem_payload") or {}).get(
        "symbolic_rules_json", state.get("problem_payload") or {}
    )
    student_raw_input = state.get("student_input", "")

    if track == "MATH":
        verdict, solved = verify_math_turn(
            draft=draft,
            problem_rules=rules,
            iteration=next_iteration,
            model_used=model_used,
            student_raw_input=student_raw_input,
        )
    elif track == "CODE":
        verdict, solved = verify_code_turn(
            draft=draft,
            problem_rules=rules,
            iteration=next_iteration,
            model_used=model_used,
            student_raw_input=student_raw_input,
            timeout_seconds=settings.ast_sandbox_timeout_seconds,
        )
    else:
        verdict, solved = verify_rag_turn(
            draft=draft,
            retrieved_chunks=state.get("retrieved_chunks") or [],
            problem_rules=rules,
            iteration=next_iteration,
            model_used=model_used,
            similarity_threshold=settings.rag_similarity_threshold,
            student_raw_input=student_raw_input,
        )

    # Combine LLM generation latency + symbolic check latency if available
    llm_latency = float(telemetry_dict.get("latency_ms", 0.0))
    verdict.latency_ms = round(llm_latency + verdict.latency_ms, 2)

    updated_audit_trail = list(state.get("audit_trail") or [])
    updated_audit_trail.append(verdict.model_dump())

    return {
        "iteration": next_iteration,
        "audit_trail": updated_audit_trail,
        "problem_solved": bool(solved and verdict.passed),
    }


def route_after_interrogation(
    state: SocraticGraphState,
) -> Literal["certified_output_node", "neural_leap_node", "circuit_breaker_node"]:
    """Conditional router enforcing MAX_SOCRATIC_RETRIES = 3."""
    settings = get_settings()
    max_retries = settings.max_socratic_retries
    audit_trail = state.get("audit_trail") or []
    iteration = state.get("iteration", 0)

    if audit_trail and audit_trail[-1].get("passed") is True:
        return "certified_output_node"

    if iteration < max_retries:
        return "neural_leap_node"

    return "circuit_breaker_node"


def certified_output_node(state: SocraticGraphState) -> dict[str, Any]:
    """Step 4 (Certified Output): Release verified Socratic reply to student."""
    latest_bundle = state.get("latest_draft") or {}
    draft_dict = latest_bundle.get("draft") or {}
    socratic_reply = str(draft_dict.get("socratic_question", "")).strip()

    if state["track"] == "RAG" and draft_dict.get("verbatim_quote"):
        quote = str(draft_dict["verbatim_quote"]).strip()
        chunk_id = draft_dict.get("cited_chunk_id")
        if quote and quote not in socratic_reply:
            socratic_reply = (
                f'{socratic_reply}\n\n[Grounded Citation — Chunk #{chunk_id}: "{quote}"]'
            )

    return {
        "final_reply": socratic_reply,
        "circuit_breaker_triggered": False,
    }


def circuit_breaker_node(state: SocraticGraphState) -> dict[str, Any]:
    """Deterministic fallback when MAX_SOCRATIC_RETRIES (3) is exhausted."""
    track = state["track"]
    payload = state.get("problem_payload") or {}
    rules = payload.get("symbolic_rules_json", payload)

    custom_fallback = rules.get("fallback_question") or payload.get("fallback_question")
    if custom_fallback:
        fallback_reply = str(custom_fallback)
    elif track == "MATH":
        fallback_reply = (
            "Let's break the mathematical expression down term by term. "
            "Which differentiation or algebraic rule applies to the very first term?"
        )
    elif track == "CODE":
        fallback_reply = (
            "Let's focus on the structure of your Python function. "
            "Have you initialized your state variable before the `for` loop and "
            "returned the result after the loop completes?"
        )
    else:
        chunks = state.get("retrieved_chunks") or []
        if chunks and float(chunks[0].get("similarity", 0.0)) >= 0.65:
            # Never paste textbook text here — that would recreate the leak the
            # verifier already rejected for MAX_SOCRATIC_RETRIES turns.
            fallback_reply = (
                "I found a relevant section in your uploaded chapter, but I want you "
                "to think it through first. Without copying the wording, what do you "
                "already understand about this idea, and which part still feels unclear?"
            )
        else:
            fallback_reply = (
                "Your question appears to fall outside the scope of the uploaded "
                "textbook chapter (similarity < 0.65). Please ask about a concept "
                "covered directly in the uploaded PDF pages."
            )

    return {
        "final_reply": fallback_reply,
        "problem_solved": False,
        "circuit_breaker_triggered": True,
    }
