"""Deterministic Track 1 (Mathematics) Symbolic Verifier powered by SymPy.

Enforces:
1. Algebraic & calculus equivalence against `target_expr` and `allowed_intermediate_exprs`.
2. Final-answer anti-leak detection across the LLM's `socratic_question`.
3. Protection against false `is_final_goal_reached_claim` hallucinations.
"""

from __future__ import annotations

import re
import time
from typing import Any
import sympy
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from backend.app.schemas.socratic import NeuralSocraticDraft, SymbolicVerdict

SYMPY_TRANSFORMATIONS = standard_transformations + (
    implicit_multiplication_application,
    convert_xor,
)

# Regex patterns to extract candidate math sub-expressions from natural language hints
BACKTICK_OR_LATEX_PATTERN = re.compile(r"`([^`]+)`|\$([^$]+)\$")
MATH_CLAUSE_PATTERN = re.compile(
    r"(?<![a-zA-Z])(?:\d+\s*\*?\s*[a-zA-Z]|[a-zA-Z]\s*(?:\*\*|\^)\s*\d+)"
    r"[0-9a-zA-Z_+\-*/^()\s]*"
)


def parse_math_expression(
    raw_expr: str,
    variables: list[str] | None = None,
) -> sympy.Expr | None:
    """Safely parse a mathematical string into a SymPy Expr."""
    if not raw_expr or not raw_expr.strip():
        return None

    cleaned = raw_expr.strip()
    if "=" in cleaned:
        cleaned = cleaned.split("=")[-1].strip()
    cleaned = cleaned.rstrip(".,;:?!")

    if not cleaned:
        return None

    local_dict: dict[str, Any] = {}
    for var_name in variables or ["x", "y", "z", "t", "n"]:
        local_dict[var_name] = sympy.Symbol(var_name)

    try:
        expr = parse_expr(
            cleaned,
            local_dict=local_dict,
            transformations=SYMPY_TRANSFORMATIONS,
            evaluate=True,
        )
        if isinstance(expr, sympy.Expr):
            return expr
        if isinstance(expr, (int, float)):
            return sympy.sympify(expr)
        return None
    except Exception:
        return None


def expressions_are_equivalent(
    expr_a: sympy.Expr | None,
    expr_b: sympy.Expr | None,
) -> bool:
    """Return True if two SymPy expressions are algebraically identical."""
    if expr_a is None or expr_b is None:
        return False
    try:
        diff = sympy.simplify(expr_a - expr_b)
        return diff == 0
    except Exception:
        return False


def extract_candidate_math_spans(text: str) -> list[str]:
    """Extract candidate math expressions from a Socratic hint for leak scanning."""
    candidates: list[str] = []

    for match in BACKTICK_OR_LATEX_PATTERN.finditer(text):
        span = (match.group(1) or match.group(2) or "").strip()
        if span:
            candidates.append(span)

    for match in MATH_CLAUSE_PATTERN.finditer(text):
        span = match.group(0).strip()
        if span:
            candidates.append(span)
            # Also trim trailing natural-language words captured after operators/spaces
            tokens = span.split()
            for end_idx in range(1, len(tokens) + 1):
                prefix = " ".join(tokens[:end_idx]).strip()
                if any(ch in prefix for ch in ("+", "-", "*", "/", "^", "x", "y")):
                    candidates.append(prefix)

    return candidates


def detect_math_answer_leak(
    socratic_question: str,
    target_expr_str: str,
    variables: list[str] | None = None,
) -> bool:
    """Return True if `socratic_question` leaks `target_expr_str` symbolically or verbatim."""
    target_sym = parse_math_expression(target_expr_str, variables=variables)
    if target_sym is None:
        return False

    canonical_target = str(sympy.simplify(target_sym)).replace(" ", "").lower()
    raw_target_norm = target_expr_str.replace(" ", "").lower()
    caret_target_norm = canonical_target.replace("**", "^")
    implicit_target_norm = canonical_target.replace("*", "")

    normalized_question = socratic_question.replace(" ", "").lower()
    for needle in {
        canonical_target,
        raw_target_norm,
        caret_target_norm,
        implicit_target_norm,
    }:
        if needle and len(needle) >= 2 and needle in normalized_question:
            return True

    for candidate in extract_candidate_math_spans(socratic_question):
        candidate_sym = parse_math_expression(candidate, variables=variables)
        if expressions_are_equivalent(candidate_sym, target_sym):
            return True

    return False


def verify_math_turn(
    draft: NeuralSocraticDraft,
    problem_rules: dict[str, Any],
    iteration: int = 1,
    model_used: str = "gemini-3.1-flash-lite",
    student_raw_input: str | None = None,
) -> tuple[SymbolicVerdict, bool]:
    """Run Step 2 deterministic SymPy verification on a NeuralSocraticDraft.

    Returns:
        tuple[SymbolicVerdict, bool]: (verdict, problem_solved)
    """
    start_ts = time.perf_counter()
    chat_mode = bool(problem_rules.get("chat_mode", False))
    target_expr_str: str = str(problem_rules.get("target_expr", "")).strip()
    allowed_intermediates: list[str] = list(
        problem_rules.get("allowed_intermediate_exprs", [])
    )
    variables: list[str] = list(problem_rules.get("variables", ["x"]))

    # Freeform chat: no fixed curriculum target — coach conversationally,
    # only reject empty replies or false "goal reached" claims without proof.
    if chat_mode and not target_expr_str:
        elapsed_ms = round((time.perf_counter() - start_ts) * 1000.0, 2)
        if not draft.socratic_question.strip():
            return (
                SymbolicVerdict(
                    iteration=iteration,
                    passed=False,
                    student_step_correct=False,
                    answer_leaked_in_hint=False,
                    rejection_reason=(
                        "Rule CHAT_REPLY violated: Socratic reply was empty."
                    ),
                    symbolic_rule_checked="SymPy Chat Coach (open-ended)",
                    model_used=model_used,
                    latency_ms=elapsed_ms,
                ),
                False,
            )
        if draft.is_final_goal_reached_claim:
            return (
                SymbolicVerdict(
                    iteration=iteration,
                    passed=False,
                    student_step_correct=False,
                    answer_leaked_in_hint=False,
                    rejection_reason=(
                        "Rule CHAT_GOAL violated: Cannot claim the final goal is "
                        "reached in open chat without a verified target expression. "
                        "Ask a guiding question instead."
                    ),
                    symbolic_rule_checked="SymPy Chat Coach (open-ended)",
                    model_used=model_used,
                    latency_ms=elapsed_ms,
                ),
                False,
            )
        return (
            SymbolicVerdict(
                iteration=iteration,
                passed=True,
                student_step_correct=False,
                answer_leaked_in_hint=False,
                rejection_reason=None,
                symbolic_rule_checked="SymPy Chat Coach (open-ended)",
                model_used=model_used,
                latency_ms=elapsed_ms,
            ),
            False,
        )

    target_sym = parse_math_expression(target_expr_str, variables=variables)
    claim_sym = parse_math_expression(draft.student_symbolic_claim, variables=variables)
    if claim_sym is None and student_raw_input:
        claim_sym = parse_math_expression(student_raw_input, variables=variables)

    is_target_reached = expressions_are_equivalent(claim_sym, target_sym)

    is_valid_intermediate = False
    if not is_target_reached and claim_sym is not None:
        for inter_str in allowed_intermediates:
            inter_sym = parse_math_expression(inter_str, variables=variables)
            if expressions_are_equivalent(claim_sym, inter_sym):
                is_valid_intermediate = True
                break

    student_step_correct = is_target_reached or is_valid_intermediate

    # Anti-Leak Check: If student has NOT solved the problem, hint must not leak target_expr
    answer_leaked = False
    if not is_target_reached:
        answer_leaked = detect_math_answer_leak(
            socratic_question=draft.socratic_question,
            target_expr_str=target_expr_str,
            variables=variables,
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
                    "LEAK VIOLATION: Your Socratic hint revealed the final answer "
                    f"('{target_expr_str}'). Rephrase as a guiding question without "
                    "stating the solution."
                ),
                symbolic_rule_checked=f"SymPy Anti-Leak Guard (target={target_expr_str})",
                model_used=model_used,
                latency_ms=elapsed_ms,
            ),
            False,
        )

    if draft.is_final_goal_reached_claim and not is_target_reached:
        return (
            SymbolicVerdict(
                iteration=iteration,
                passed=False,
                student_step_correct=student_step_correct,
                answer_leaked_in_hint=False,
                rejection_reason=(
                    "Rule GOAL_EQUIVALENCE violated: Draft claimed "
                    "is_final_goal_reached_claim=True, but SymPy proved "
                    f"'{draft.student_symbolic_claim}' != '{target_expr_str}'."
                ),
                symbolic_rule_checked=f"SymPy Goal Equivalence (target={target_expr_str})",
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
                f"SymPy Equivalence & Anti-Leak Certified (target={target_expr_str})"
            ),
            model_used=model_used,
            latency_ms=elapsed_ms,
        ),
        is_target_reached,
    )
