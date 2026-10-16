"""Turn-context helpers: open-chat payloads and ownership-scoped ground truth."""

from __future__ import annotations

from typing import Any
from fastapi import HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.models.curriculum import ProblemItem, TextbookChapter
from backend.app.models.user import User
from backend.app.routers.subjects import seed_default_curriculum
from backend.app.schemas.socratic import SocraticTurnRequest
from backend.app.services.gemini_router import GeminiRouter
from backend.app.services.rag_ingestion import retrieve_top_k_chunks


def open_chat_payload(track: str, student_input: str) -> dict[str, Any]:
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


async def resolve_owned_chapter(
    session: AsyncSession,
    current_user: User,
    chapter_id: int | None,
) -> TextbookChapter:
    """Resolve a textbook chapter that belongs to the authenticated user only."""
    assert current_user.id is not None
    stmt = select(TextbookChapter).where(TextbookChapter.user_id == current_user.id)
    if chapter_id is not None:
        stmt = stmt.where(TextbookChapter.id == chapter_id)
    chapter = (await session.exec(stmt)).first()
    if chapter is None or chapter.id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Textbook chapter not found. Please upload a PDF chapter first.",
        )
    return chapter


async def resolve_problem_and_chunks(
    payload: SocraticTurnRequest,
    session: AsyncSession,
    gemini_router: GeminiRouter,
    current_user: User,
) -> tuple[dict[str, Any], list[dict[str, Any]], int | None, int | None]:
    """Load practice-problem rules, open-chat payload, or owned Top-3 RAG chunks."""
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
            resolved_problem_id = None
            problem_payload = open_chat_payload(payload.track, payload.student_input)
            rules = dict(problem_payload["symbolic_rules_json"])
            rules["chat_mode"] = True
            problem_payload["symbolic_rules_json"] = rules
    else:
        chapter = await resolve_owned_chapter(
            session=session,
            current_user=current_user,
            chapter_id=payload.chapter_id,
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
