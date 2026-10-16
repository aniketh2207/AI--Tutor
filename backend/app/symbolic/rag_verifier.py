"""Deterministic Track 3 (Grounded Textbook RAG) Symbolic Verifier.

Enforces:
1. Out-of-Scope Guard (`max_similarity >= 0.65` cosine similarity threshold).
2. Verbatim Citation Guard (`cited_chunk_id` in Top-3 chunks and exact substring match).
3. Anti-Leak Guard (prevents copying >60% of the target answer span into `socratic_question`).
"""

from __future__ import annotations

from difflib import SequenceMatcher
import time
from typing import Any

from backend.app.schemas.socratic import NeuralSocraticDraft, SymbolicVerdict


def normalize_whitespace_case(text: str) -> str:
    """Collapse consecutive whitespace and lowercase for deterministic substring check."""
    return " ".join(text.strip().split()).lower()


def verify_verbatim_citation(
    cited_chunk_id: int | None,
    verbatim_quote: str | None,
    retrieved_chunks: list[dict[str, Any]],
) -> tuple[bool, dict[str, Any] | None]:
    """Verify `cited_chunk_id` is in `retrieved_chunks` and `verbatim_quote` is an exact substring."""
    if cited_chunk_id is None or not verbatim_quote or not verbatim_quote.strip():
        return False, None

    matched_chunk: dict[str, Any] | None = None
    for chunk in retrieved_chunks[:3]:
        if chunk.get("id") == cited_chunk_id:
            matched_chunk = chunk
            break

    if matched_chunk is None:
        return False, None

    norm_quote = normalize_whitespace_case(verbatim_quote)
    norm_content = normalize_whitespace_case(str(matched_chunk.get("content", "")))
    if not norm_quote or norm_quote not in norm_content:
        return False, matched_chunk

    return True, matched_chunk


def detect_rag_answer_span_leak(
    socratic_question: str,
    target_answer_span: str,
    max_copy_ratio: float = 0.60,
) -> bool:
    """Return True if `socratic_question` verbatim-copies >60% of `target_answer_span`."""
    norm_q = normalize_whitespace_case(socratic_question)
    norm_target = normalize_whitespace_case(target_answer_span)
    if not norm_q or not norm_target or len(norm_target) < 15:
        return False

    matcher = SequenceMatcher(None, norm_q, norm_target)
    longest_match = matcher.find_longest_match(0, len(norm_q), 0, len(norm_target))
    copied_ratio = longest_match.size / float(len(norm_target))
    return copied_ratio > max_copy_ratio


def check_student_concept_mastery(
    student_claim: str,
    student_raw_input: str | None,
    target_concept: str | None,
) -> bool:
    """Determine if the student's input/claim identifies the core target concept."""
    if not target_concept or not target_concept.strip():
        return False

    combined_student = normalize_whitespace_case(
        f"{student_claim} {student_raw_input or ''}"
    )
    norm_concept = normalize_whitespace_case(target_concept)
    if norm_concept in combined_student:
        return True

    concept_tokens = [
        tok for tok in norm_concept.split() if len(tok) > 3
    ]
    if not concept_tokens:
        return False

    matched_tokens = sum(1 for tok in concept_tokens if tok in combined_student)
    return (matched_tokens / float(len(concept_tokens))) >= 0.75


def verify_rag_turn(
    draft: NeuralSocraticDraft,
    retrieved_chunks: list[dict[str, Any]],
    problem_rules: dict[str, Any] | None = None,
    iteration: int = 1,
    model_used: str = "gemini-3.1-flash-lite",
    similarity_threshold: float = 0.65,
    student_raw_input: str | None = None,
) -> tuple[SymbolicVerdict, bool]:
    """Run Step 2 deterministic RAG verification on a NeuralSocraticDraft."""
    start_ts = time.perf_counter()
    rules = problem_rules or {}
    top_chunks = retrieved_chunks[:3]

    max_similarity = max(
        (float(c.get("similarity", 0.0)) for c in top_chunks),
        default=0.0,
    )

    # 1. Out-of-Scope Check
    if not top_chunks or max_similarity < similarity_threshold:
        elapsed_ms = round((time.perf_counter() - start_ts) * 1000.0, 2)
        return (
            SymbolicVerdict(
                iteration=iteration,
                passed=False,
                student_step_correct=False,
                answer_leaked_in_hint=False,
                rejection_reason=(
                    f"OUT_OF_SCOPE VIOLATION: Maximum retrieved chunk similarity "
                    f"({max_similarity:.2f}) is below threshold ({similarity_threshold})."
                ),
                symbolic_rule_checked=(
                    f"RAG Cosine Similarity Guard (max={max_similarity:.2f} < {similarity_threshold})"
                ),
                model_used=model_used,
                latency_ms=elapsed_ms,
            ),
            False,
        )

    # 2. Verbatim Citation Check
    citation_ok, cited_chunk = verify_verbatim_citation(
        cited_chunk_id=draft.cited_chunk_id,
        verbatim_quote=draft.verbatim_quote,
        retrieved_chunks=top_chunks,
    )
    if not citation_ok or cited_chunk is None:
        elapsed_ms = round((time.perf_counter() - start_ts) * 1000.0, 2)
        return (
            SymbolicVerdict(
                iteration=iteration,
                passed=False,
                student_step_correct=False,
                answer_leaked_in_hint=False,
                rejection_reason=(
                    "CITATION VIOLATION: verbatim_quote must be an exact "
                    "character-for-character substring of the retrieved chunk."
                ),
                symbolic_rule_checked="RAG Verbatim Substring Citation Guard",
                model_used=model_used,
                latency_ms=elapsed_ms,
            ),
            False,
        )

    target_concept = str(
        rules.get("target_concept") or rules.get("target_answer_span") or ""
    ).strip()
    student_step_correct = check_student_concept_mastery(
        student_claim=draft.student_symbolic_claim,
        student_raw_input=student_raw_input,
        target_concept=target_concept,
    )
    if not target_concept and draft.is_final_goal_reached_claim:
        student_step_correct = True

    # 3. Anti-Leak Check (>60% verbatim copy of target answer span before mastery)
    target_span_for_leak = target_concept or str(draft.verbatim_quote or "")
    answer_leaked = False
    if not student_step_correct and target_span_for_leak:
        answer_leaked = detect_rag_answer_span_leak(
            socratic_question=draft.socratic_question,
            target_answer_span=target_span_for_leak,
            max_copy_ratio=0.60,
        )

    elapsed_ms = round((time.perf_counter() - start_ts) * 1000.0, 2)

    if answer_leaked:
        return (
            SymbolicVerdict(
                iteration=iteration,
                passed=False,
                student_step_correct=student_step_correct,
                answer_leaked_in_hint=True,
                rejection_reason=(
                    "LEAK VIOLATION: Your Socratic hint verbatim-copied more than 60% "
                    "of the target textbook answer span before the student identified "
                    "the core concept. Ask a guiding question instead."
                ),
                symbolic_rule_checked="RAG Anti-Leak Span Guard (<=60% copy ratio)",
                model_used=model_used,
                latency_ms=elapsed_ms,
            ),
            False,
        )

    if draft.is_final_goal_reached_claim and not student_step_correct:
        return (
            SymbolicVerdict(
                iteration=iteration,
                passed=False,
                student_step_correct=False,
                answer_leaked_in_hint=False,
                rejection_reason=(
                    "Rule RAG_CONCEPT_MASTERY violated: Student has not yet stated "
                    f"the core textbook concept ('{target_concept}')."
                ),
                symbolic_rule_checked="RAG Concept Mastery Guard",
                model_used=model_used,
                latency_ms=elapsed_ms,
            ),
            False,
        )

    return (
        SymbolicVerdict(
            iteration=iteration,
            passed=True,
            student_step_correct=student_step_correct,
            answer_leaked_in_hint=False,
            rejection_reason=None,
            symbolic_rule_checked=(
                f"RAG Verbatim Citation & Similarity Certified (chunk_id={draft.cited_chunk_id}, "
                f"sim={max_similarity:.2f})"
            ),
            model_used=model_used,
            latency_ms=elapsed_ms,
        ),
        student_step_correct and draft.is_final_goal_reached_claim,
    )
