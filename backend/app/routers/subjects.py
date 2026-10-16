"""Subjects & Curriculum router: track enrollment and seeded problem retrieval."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.database import get_session
from backend.app.models.curriculum import ProblemItem
from backend.app.models.user import SubjectEnrollment, User
from backend.app.schemas.auth import (
    EnrollmentResponse,
    ProblemItemResponse,
    SubjectEnrollRequest,
    TrackType,
)
from backend.app.services.auth_service import get_current_user

router = APIRouter(prefix="/api/subjects", tags=["Subjects & Curriculum"])

DEFAULT_CURRICULUM_PROBLEMS: list[dict[str, Any]] = [
    {
        "slug": "math-deriv-poly",
        "track": "MATH",
        "title": "Power Rule Derivative of a Cubic Polynomial",
        "prompt": (
            "Find the first derivative f'(x) of the function "
            "f(x) = x**3 + 2*x with respect to x."
        ),
        "difficulty": "BEGINNER",
        "symbolic_rules_json": {
            "variables": ["x"],
            "target_expr": "3*x**2 + 2",
            "allowed_intermediate_exprs": ["3*x**2", "2", "x**3", "2*x"],
            "fallback_question": (
                "Apply the power rule d/dx[x^n] = n*x^(n-1) to each term of "
                "x**3 + 2*x separately. What is the derivative of the first term x**3?"
            ),
        },
    },
    {
        "slug": "math-integral-linear",
        "track": "MATH",
        "title": "Antiderivative of a Linear Function",
        "prompt": (
            "Find the antiderivative F(x) of g(x) = 2*x + 4 with respect to x "
            "(for C = 0)."
        ),
        "difficulty": "INTERMEDIATE",
        "symbolic_rules_json": {
            "variables": ["x"],
            "target_expr": "x**2 + 4*x",
            "allowed_intermediate_exprs": ["x**2", "4*x", "2*x**2/2"],
            "fallback_question": (
                "Recall the reverse power rule: the antiderivative of x^n is "
                "x^(n+1)/(n+1). What do you get when you integrate 2*x first?"
            ),
        },
    },
    {
        "slug": "code-array-sum-loop",
        "track": "CODE",
        "title": "Iterative Array Sum (Without Built-in sum)",
        "prompt": (
            "Write a Python function `sum_elements(nums)` that computes and returns "
            "the sum of all integers in `nums` using a `for` loop. "
            "Do NOT use `while` loops or the built-in `sum()` function."
        ),
        "difficulty": "BEGINNER",
        "symbolic_rules_json": {
            "function_name": "sum_elements",
            "required_ast_nodes": ["FunctionDef", "For", "Return"],
            "forbidden_ast_nodes": ["While"],
            "forbidden_calls": ["sum"],
            "test_cases": [
                {"input": [[1, 2, 3, 4]], "expected": 10},
                {"input": [[-5, 5, 12]], "expected": 12},
                {"input": [[]], "expected": 0},
            ],
            "fallback_question": (
                "Initialize an accumulator variable before your `for` loop, add each "
                "element to it inside the loop, and `return` the accumulator at the end."
            ),
        },
    },
    {
        "slug": "code-max-element-loop",
        "track": "CODE",
        "title": "Iterative Maximum Finder (Without max/sort)",
        "prompt": (
            "Write a Python function `find_max(nums)` that returns the largest element "
            "in a non-empty list `nums` using a `for` loop and an `if` comparison. "
            "Do NOT use `max()`, `sorted()`, or `.sort()`."
        ),
        "difficulty": "INTERMEDIATE",
        "symbolic_rules_json": {
            "function_name": "find_max",
            "required_ast_nodes": ["FunctionDef", "For", "If", "Return"],
            "forbidden_ast_nodes": ["While"],
            "forbidden_calls": ["max", "sorted", "sort"],
            "test_cases": [
                {"input": [[3, 9, 2, 7]], "expected": 9},
                {"input": [[-10, -3, -25]], "expected": -3},
                {"input": [[42]], "expected": 42},
            ],
            "fallback_question": (
                "Start by tracking the first element `nums[0]` as your current maximum, "
                "then iterate through `nums` with a `for` loop and update it inside an `if` block."
            ),
        },
    },
]


async def seed_default_curriculum(session: AsyncSession) -> list[ProblemItem]:
    """Idempotently seed default Math and Coding curriculum problems."""
    seeded: list[ProblemItem] = []
    for item_data in DEFAULT_CURRICULUM_PROBLEMS:
        result = await session.exec(
            select(ProblemItem).where(ProblemItem.slug == item_data["slug"])
        )
        existing = result.first()
        if existing is None:
            existing = ProblemItem(**item_data)
            session.add(existing)
        seeded.append(existing)
    await session.commit()
    for problem in seeded:
        await session.refresh(problem)
    return seeded


@router.post("/enroll", response_model=EnrollmentResponse)
async def enroll_in_subject(
    payload: SubjectEnrollRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> EnrollmentResponse:
    """Enroll the authenticated student in a learning track (idempotent)."""
    assert current_user.id is not None
    existing_query = await session.exec(
        select(SubjectEnrollment).where(
            SubjectEnrollment.user_id == current_user.id,
            SubjectEnrollment.track == payload.track,
        )
    )
    enrollment = existing_query.first()
    if enrollment is None:
        enrollment = SubjectEnrollment(
            user_id=current_user.id,
            track=payload.track,
        )
        session.add(enrollment)
        await session.commit()
        await session.refresh(enrollment)
    return EnrollmentResponse.model_validate(enrollment)


@router.get("/enrollments", response_model=list[EnrollmentResponse])
async def list_enrollments(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[EnrollmentResponse]:
    """List all learning tracks the current student is enrolled in."""
    assert current_user.id is not None
    result = await session.exec(
        select(SubjectEnrollment).where(SubjectEnrollment.user_id == current_user.id)
    )
    return [EnrollmentResponse.model_validate(row) for row in result.all()]


@router.get("/problems", response_model=list[ProblemItemResponse])
async def list_curriculum_problems(
    track: TrackType | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[ProblemItemResponse]:
    """Return seeded curriculum problems, optionally filtered by track."""
    await seed_default_curriculum(session)
    stmt = select(ProblemItem)
    if track is not None:
        stmt = stmt.where(ProblemItem.track == track)
    result = await session.exec(stmt)
    return [ProblemItemResponse.model_validate(p) for p in result.all()]
