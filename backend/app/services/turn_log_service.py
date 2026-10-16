"""Allocate unique (session_id, turn_index) values under concurrent writers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.models.session import SocraticTurnLog, TutorSession
from backend.app.schemas.socratic import SocraticTurnResponse


async def _next_turn_index(session: AsyncSession, session_id: str) -> int:
    """Return max(turn_index)+1 for the session (0-safe)."""
    result = await session.exec(
        select(func.coalesce(func.max(SocraticTurnLog.turn_index), 0)).where(
            SocraticTurnLog.session_id == session_id
        )
    )
    return int(result.one()) + 1


async def persist_turn_log(
    session: AsyncSession,
    *,
    tutor_session: TutorSession,
    student_input: str,
    turn_response: SocraticTurnResponse,
    resolved_problem_id: int | None,
    resolved_chapter_id: int | None,
) -> None:
    """Insert a turn log with unique (session_id, turn_index), retrying on conflict."""
    audit_payload: list[dict[str, Any]] = [
        v.model_dump() for v in turn_response.audit_trail
    ]

    last_error: Exception | None = None
    for _ in range(5):
        next_idx = await _next_turn_index(session, tutor_session.id)
        turn_log = SocraticTurnLog(
            session_id=tutor_session.id,
            turn_index=next_idx,
            student_input=student_input,
            socratic_reply=turn_response.socratic_reply,
            problem_solved=turn_response.problem_solved,
            iterations_taken=turn_response.iterations_taken,
            circuit_breaker_triggered=turn_response.circuit_breaker_triggered,
            audit_trail_json=audit_payload,
        )
        session.add(turn_log)

        if turn_response.problem_solved:
            tutor_session.is_solved = True
        if resolved_problem_id is not None:
            tutor_session.problem_id = resolved_problem_id
        if resolved_chapter_id is not None:
            tutor_session.chapter_id = resolved_chapter_id
        tutor_session.updated_at = datetime.now(timezone.utc)
        session.add(tutor_session)

        try:
            await session.commit()
            return
        except IntegrityError as exc:
            last_error = exc
            await session.rollback()
            # Re-attach tutor_session after rollback for the next attempt.
            session.add(tutor_session)

    raise RuntimeError(
        f"Failed to allocate unique turn_index for session {tutor_session.id}"
    ) from last_error
