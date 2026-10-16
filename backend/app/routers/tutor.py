"""Socratic Tutor Router: conversational turn execution & session audit history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.database import get_session
from backend.app.graph.workflow import execute_socratic_turn
from backend.app.models.session import SocraticTurnLog, TutorSession
from backend.app.models.user import User
from backend.app.routers.tutor_context import resolve_problem_and_chunks
from backend.app.schemas.socratic import (
    SessionHistoryResponse,
    SocraticTurnRequest,
    SocraticTurnResponse,
    SymbolicVerdict,
    TurnHistoryItem,
)
from backend.app.services.auth_service import get_current_user
from backend.app.services.gemini_router import GeminiRouter, get_gemini_router
from backend.app.services.rate_limit_service import enforce_turn_budgets
from backend.app.services.turn_log_service import persist_turn_log

router = APIRouter(prefix="/api/tutor", tags=["Socratic Tutor"])


async def _load_conversation_history(
    session: AsyncSession,
    session_id: str,
) -> list[dict[str, str]]:
    """Load prior student/tutor turns for multi-turn chat continuity."""
    logs_res = await session.exec(
        select(SocraticTurnLog)
        .where(SocraticTurnLog.session_id == session_id)
        .order_by(SocraticTurnLog.turn_index)  # type: ignore[arg-type]
    )
    history: list[dict[str, str]] = []
    for log in logs_res.all():
        history.append({"role": "student", "content": log.student_input})
        history.append({"role": "tutor", "content": log.socratic_reply})
    return history


@router.post("/turn", response_model=SocraticTurnResponse)
async def submit_socratic_turn(
    payload: SocraticTurnRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    gemini_router: GeminiRouter = Depends(get_gemini_router),
) -> SocraticTurnResponse:
    """Execute the 4-Step Neuro-Symbolic Socratic Loop for a chat message."""
    assert current_user.id is not None
    await enforce_turn_budgets(session, current_user.id)

    (
        problem_payload,
        retrieved_chunks,
        resolved_problem_id,
        resolved_chapter_id,
    ) = await resolve_problem_and_chunks(
        payload, session, gemini_router, current_user
    )

    tutor_session: TutorSession | None = None
    if payload.session_id:
        res = await session.exec(
            select(TutorSession).where(
                TutorSession.id == payload.session_id,
                TutorSession.user_id == current_user.id,
            )
        )
        tutor_session = res.first()

    if tutor_session is None:
        tutor_session = TutorSession(
            id=payload.session_id or TutorSession().id,
            user_id=current_user.id,
            track=payload.track,
            problem_id=resolved_problem_id,
            chapter_id=resolved_chapter_id,
        )
        session.add(tutor_session)
        await session.commit()

    conversation_history = await _load_conversation_history(session, tutor_session.id)

    turn_response = await execute_socratic_turn(
        session_id=tutor_session.id,
        track=payload.track,
        student_input=payload.student_input,
        problem_payload=problem_payload,
        retrieved_chunks=retrieved_chunks,
        conversation_history=conversation_history,
        router=gemini_router,
    )

    await persist_turn_log(
        session,
        tutor_session=tutor_session,
        student_input=payload.student_input,
        turn_response=turn_response,
        resolved_problem_id=resolved_problem_id,
        resolved_chapter_id=resolved_chapter_id,
    )
    return turn_response


@router.get("/session/{session_id}/history", response_model=SessionHistoryResponse)
async def get_session_history(
    session_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SessionHistoryResponse:
    """Retrieve full turn history and Neuro-Symbolic audit trails for a tutoring session."""
    res = await session.exec(
        select(TutorSession).where(
            TutorSession.id == session_id,
            TutorSession.user_id == current_user.id,
        )
    )
    tutor_session = res.first()
    if tutor_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tutor session '{session_id}' not found.",
        )

    logs_res = await session.exec(
        select(SocraticTurnLog)
        .where(SocraticTurnLog.session_id == session_id)
        .order_by(SocraticTurnLog.turn_index)  # type: ignore[arg-type]
    )
    turn_logs = list(logs_res.all())

    turns = [
        TurnHistoryItem(
            turn_index=log.turn_index,
            student_input=log.student_input,
            socratic_reply=log.socratic_reply,
            problem_solved=log.problem_solved,
            iterations_taken=log.iterations_taken,
            circuit_breaker_triggered=log.circuit_breaker_triggered,
            audit_trail=[
                SymbolicVerdict.model_validate(item)
                for item in log.audit_trail_json
            ],
            created_at=log.created_at,
        )
        for log in turn_logs
    ]

    return SessionHistoryResponse(
        session_id=tutor_session.id,
        track=tutor_session.track,  # type: ignore[arg-type]
        is_solved=tutor_session.is_solved,
        turns=turns,
    )

