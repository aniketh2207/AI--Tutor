"""Pydantic v2 Neuro-Symbolic contracts defined in document.md Section 5.1."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class NeuralSocraticDraft(BaseModel):
    """Strict structured JSON output schema enforced on all Gemini Router calls."""

    student_intent_summary: str = Field(
        description="Brief analysis of what the student attempted."
    )
    student_symbolic_claim: str = Field(
        description=(
            "For MATH: valid SymPy expression representing the student's current step "
            "(e.g., '3*x**2'). "
            "For CODE: the Python snippet submitted. "
            "For RAG: key claim extracted from student's text."
        )
    )
    is_final_goal_reached_claim: bool = Field(
        description="True ONLY if the student explicitly arrived at the complete final answer."
    )
    cited_chunk_id: Optional[int] = Field(
        default=None,
        description="REQUIRED for RAG track: exact ID of the retrieved textbook chunk.",
    )
    verbatim_quote: Optional[str] = Field(
        default=None,
        description=(
            "REQUIRED for RAG track: exact 100% verbatim substring from the chunk "
            "supporting the hint."
        ),
    )
    socratic_question: str = Field(
        description=(
            "The guiding Socratic question or hint for the student. "
            "MUST NOT contain or leak the final answer."
        )
    )


class SymbolicVerdict(BaseModel):
    """Deterministic symbolic verification verdict for a single Socratic loop iteration."""

    iteration: int
    passed: bool
    student_step_correct: bool
    answer_leaked_in_hint: bool
    rejection_reason: Optional[str] = None
    symbolic_rule_checked: str
    model_used: str
    latency_ms: float


class SocraticTurnResponse(BaseModel):
    """Certified response released to the student at Step 4 of the Socratic cycle."""

    session_id: str
    track: Literal["MATH", "CODE", "RAG"]
    socratic_reply: str
    problem_solved: bool
    iterations_taken: int
    circuit_breaker_triggered: bool
    audit_trail: List[SymbolicVerdict]


class ModelTelemetry(BaseModel):
    """Telemetry captured by the Multi-Model Gemini Router per invocation."""

    model_used: str
    attempt_index: int
    fallback_triggered: bool
    failed_models: List[str] = Field(default_factory=list)
    latency_ms: float


class SocraticTurnRequest(BaseModel):
    """Incoming chat message from the student to execute a Socratic turn.

    Omit `problem_id` for freeform chat (student asks their own question).
    Provide `problem_id` only when the student opts into a practice problem.
    """

    session_id: Optional[str] = None
    track: Literal["MATH", "CODE", "RAG"]
    problem_id: Optional[int] = None
    chapter_id: Optional[int] = None
    student_input: str = Field(min_length=1, max_length=8000)
    chat_mode: bool = Field(
        default=True,
        description=(
            "True for conversational tutoring where the student asks freely. "
            "False when verifying against a seeded practice problem's ground truth."
        ),
    )


class TurnHistoryItem(BaseModel):
    """Historical turn entry with its full Neuro-Symbolic audit trail."""

    model_config = ConfigDict(from_attributes=True)

    turn_index: int
    student_input: str
    socratic_reply: str
    problem_solved: bool
    iterations_taken: int
    circuit_breaker_triggered: bool
    audit_trail: List[SymbolicVerdict]
    created_at: datetime


class SessionHistoryResponse(BaseModel):
    """Full session history and audit telemetry."""

    session_id: str
    track: Literal["MATH", "CODE", "RAG"]
    is_solved: bool
    turns: List[TurnHistoryItem]
