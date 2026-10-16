"""LangGraph Socratic State definition (`document.md` Section 6)."""

from __future__ import annotations

from typing import Any, Literal, Optional, TypedDict


class SocraticGraphState(TypedDict):
    """TypedDict state flowing through the 4-Step Neuro-Symbolic Socratic Cycle."""

    session_id: str
    track: Literal["MATH", "CODE", "RAG"]
    problem_payload: dict[str, Any]
    student_input: str
    conversation_history: list[dict[str, str]]
    retrieved_chunks: list[dict[str, Any]]
    iteration: int
    latest_draft: Optional[dict[str, Any]]
    audit_trail: list[dict[str, Any]]
    final_reply: str
    problem_solved: bool
    circuit_breaker_triggered: bool
