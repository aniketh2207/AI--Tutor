"""Socratic Tutor Router: conversational turn execution & session audit history."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.database import get_session
from backend.app.graph.workflow import execute_socratic_turn
from backend.app.models.curriculum import ProblemItem, TextbookChapter
from backend.app.models.session import SocraticTurnLog, TutorSession
from backend.app.models.user import User
from backend.app.routers.subjects import seed_default_curriculum
from backend.app.schemas.socratic import (
    SessionHistoryResponse,
    SocraticTurnRequest,
    SocraticTurnResponse,
    SymbolicVerdict,
    TurnHistoryItem,
)
from backend.app.services.auth_service import get_current_user
from backend.app.services.gemini_router import GeminiRouter, get_gemini_router
from backend.app.services.rag_ingestion import retrieve_top_k_chunks

router = APIRouter(prefix="/api/tutor", tags=["Socratic Tutor"])


def _open_chat_payload(track: str, student_input: str) -> dict[str, Any]:
    """Build a freeform chat ground-truth payload when no practice problem is selected."""
    if track == "MATH":
        return {
            "id": None,
            "slug": "open-math-chat",
            "title": "Open Math Chat",
            "prompt": (
                "The student is chatting freely about mathematics. "
                f"Their latest message: {student_input[:500]}"
            ),
            "symbolic_rules_json": {
                "chat_mode": True,
                "variables": ["x", "y", "z", "t", "n"],
                "target_expr": "",
                "allowed_intermediate_exprs": [],
                "fallback_question": (
                    "What part of this math problem feels unclear — "
                    "the setup, the rule to apply, or the algebra?"
                ),
            },
        }
    return {
        "id": None,
        "slug": "open-code-chat",
        "title": "Open Coding Chat",
        "prompt": (
            "The student is chatting freely about Python / DSA. "
            f"Their latest message: {student_input[:500]}"
        ),
        "symbolic_rules_json": {
            "chat_mode": True,
            "function_name": "",
            "required_ast_nodes": [],
            "forbidden_ast_nodes": [],
            "forbidden_calls": ["eval", "exec"],
            "test_cases": [],
            "fallback_question": (
                "What are you trying to build — the overall algorithm, "
                "a specific loop, or how to structure the function?"
            ),
        },
    }


async def _resolve_problem_and_chunks(
    payload: SocraticTurnRequest,
    session: AsyncSession,
    gemini_router: GeminiRouter,
) -> tuple[dict[str, Any], list[dict[str, Any]], int | None, int | None]:
    """Load practice-problem rules, open-chat payload, or Top-3 RAG chunks."""
    await seed_default_curriculum(session)
    problem_payload: dict[str, Any] = {}
    retrieved_chunks: list[dict[str, Any]] = []
    resolved_problem_id = payload.problem_id
    resolved_chapter_id = payload.chapter_id

    if payload.track in ("MATH", "CODE"):
        if payload.problem_id is not None:
            problem = (
                await session.exec(
                    select(ProblemItem).where(ProblemItem.id == payload.problem_id)
                )
            ).first()
            if problem is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Curriculum problem not found for track {payload.track}.",
                )
            resolved_problem_id = problem.id
            rules = dict(problem.symbolic_rules_json or {})
            rules["chat_mode"] = False
            problem_payload = {
                "id": problem.id,
                "slug": problem.slug,
                "title": problem.title,
                "prompt": problem.prompt,
                "symbolic_rules_json": rules,
            }
        else:
            # Freeform chat — student asks their own question
            resolved_problem_id = None
            problem_payload = _open_chat_payload(payload.track, payload.student_input)
            rules = dict(problem_payload["symbolic_rules_json"])
            rules["chat_mode"] = True
            problem_payload["symbolic_rules_json"] = rules
    else:
        stmt_ch = select(TextbookChapter)
        if payload.chapter_id is not None:
            stmt_ch = stmt_ch.where(TextbookChapter.id == payload.chapter_id)
        chapter = (await session.exec(stmt_ch)).first()
        if chapter is None or chapter.id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Textbook chapter not found. Please upload a PDF chapter first.",
            )
        resolved_chapter_id = chapter.id
        retrieved_chunks = await retrieve_top_k_chunks(
            session=session,
            chapter_id=chapter.id,
            query_text=payload.student_input,
            top_k=3,
            router=gemini_router,
        )
        problem_payload = {
            "chapter_id": chapter.id,
            "title": chapter.title,
            "prompt": f"Socratic chat grounded in '{chapter.title}'.",
            "symbolic_rules_json": {
                "chat_mode": True,
                "target_concept": chapter.target_concept or "",
            },
        }

    return problem_payload, retrieved_chunks, resolved_problem_id, resolved_chapter_id


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
    (
        problem_payload,
        retrieved_chunks,
        resolved_problem_id,
        resolved_chapter_id,
    ) = await _resolve_problem_and_chunks(payload, session, gemini_router)

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
        await session.refresh(tutor_session)

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

    existing_turns_res = await session.exec(
        select(SocraticTurnLog).where(SocraticTurnLog.session_id == tutor_session.id)
    )
    next_turn_idx = len(list(existing_turns_res.all())) + 1

    turn_log = SocraticTurnLog(
        session_id=tutor_session.id,
        turn_index=next_turn_idx,
        student_input=payload.student_input,
        socratic_reply=turn_response.socratic_reply,
        problem_solved=turn_response.problem_solved,
        iterations_taken=turn_response.iterations_taken,
        circuit_breaker_triggered=turn_response.circuit_breaker_triggered,
        audit_trail_json=[v.model_dump() for v in turn_response.audit_trail],
    )
    session.add(turn_log)

    if turn_response.problem_solved:
        tutor_session.is_solved = True
    # Keep optional practice problem / chapter binding up to date
    if resolved_problem_id is not None:
        tutor_session.problem_id = resolved_problem_id
    if resolved_chapter_id is not None:
        tutor_session.chapter_id = resolved_chapter_id
    tutor_session.updated_at = datetime.now(timezone.utc)
    session.add(tutor_session)

    await session.commit()
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
