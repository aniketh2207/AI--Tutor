"""SQLModel database models for Tutor Sessions and Socratic Turn Audit Logs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
import uuid
from sqlalchemy import Column, JSON, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def new_session_uuid() -> str:
    """Generate a unique string UUID for a tutoring session."""
    return str(uuid.uuid4())


class TutorSession(SQLModel, table=True):
    """Stateful tutoring session linking a student to a track and problem/chapter."""

    __tablename__ = "tutor_sessions"

    id: str = Field(default_factory=new_session_uuid, primary_key=True, max_length=64)
    user_id: int = Field(foreign_key="users.id", index=True)
    track: str = Field(index=True, max_length=16)  # "MATH", "CODE", or "RAG"
    problem_id: Optional[int] = Field(default=None, foreign_key="problem_items.id", index=True)
    chapter_id: Optional[int] = Field(
        default=None, foreign_key="textbook_chapters.id", index=True
    )
    is_solved: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SocraticTurnLog(SQLModel, table=True):
    """Immutable audit log of a completed 4-step Neuro-Symbolic Socratic turn."""

    __tablename__ = "socratic_turn_logs"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "turn_index",
            name="uq_socratic_turn_session_index",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="tutor_sessions.id", index=True, max_length=64)
    turn_index: int = Field(default=1)
    student_input: str = Field(sa_column=Column(Text, nullable=False))
    socratic_reply: str = Field(sa_column=Column(Text, nullable=False))
    problem_solved: bool = Field(default=False)
    iterations_taken: int = Field(default=1)
    circuit_breaker_triggered: bool = Field(default=False)
    audit_trail_json: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=utc_now)
