"""Deterministic Track 2 (Python & DSA Logic) Symbolic Verifier.

Enforces:
1. Python `ast.parse()` structural verification (`required_ast_nodes`, `forbidden_ast_nodes`, `forbidden_calls`).
2. Anti-leak detection on `socratic_question` (blocks markdown code blocks and `ast.FunctionDef` leaks).
3. Isolated `subprocess.run` sandbox execution (`-I`, `timeout=2.0` seconds) against `test_cases`.
"""

from __future__ import annotations

import ast
import re
import textwrap
import time
from typing import Any

from backend.app.config import get_settings
from backend.app.schemas.socratic import NeuralSocraticDraft, SymbolicVerdict
from backend.app.symbolic.ast_sandbox import run_code_in_sandbox

# Re-export for tests and package consumers
__all__ = [
    "inspect_ast_structure",
    "detect_code_leak_in_hint",
    "run_code_in_sandbox",
    "verify_code_turn",
]

CODE_FENCE_PATTERN = re.compile(r"```(?:python|py)?[\s\S]*?```", re.IGNORECASE)
DEF_LINE_PATTERN = re.compile(r"^\s*def\s+[a-zA-Z_][a-zA-Z0-9_]*\s*\(", re.MULTILINE)


def inspect_ast_structure(
    code_str: str,
    required_ast_nodes: list[str] | None = None,
    forbidden_ast_nodes: list[str] | None = None,
    forbidden_calls: list[str] | None = None,
) -> tuple[bool, str | None]:
    """Statically verify Python code structure via `ast.parse()` without executing it."""
    if not code_str or not code_str.strip():
        return False, "AST_SYNTAX_ERROR: Student code submission is empty."

    try:
        tree = ast.parse(code_str)
    except SyntaxError as exc:
        return False, f"AST_SYNTAX_ERROR: Line {exc.lineno}: {exc.msg}"

    present_node_types: set[str] = {type(node).__name__ for node in ast.walk(tree)}
    called_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called_names.add(node.func.attr)

    for forbidden_node in forbidden_ast_nodes or []:
        if forbidden_node in present_node_types:
            return (
                False,
                f"AST_FORBIDDEN_NODE: Forbidden construct '{forbidden_node}' detected.",
            )

    for forbidden_fn in forbidden_calls or []:
        if forbidden_fn in called_names:
            return (
                False,
                f"AST_FORBIDDEN_CALL: Forbidden function/method call '{forbidden_fn}()' detected.",
            )

    for required_node in required_ast_nodes or []:
        if required_node not in present_node_types:
            return (
                False,
                f"AST_MISSING_NODE: Required construct '{required_node}' is missing.",
            )

    return True, None


def detect_code_leak_in_hint(socratic_question: str) -> bool:
    """Return True if `socratic_question` contains markdown code fences or a FunctionDef."""
    if not socratic_question:
        return False

    if CODE_FENCE_PATTERN.search(socratic_question):
        return True

    if DEF_LINE_PATTERN.search(socratic_question):
        lines = socratic_question.splitlines()
        for idx, line in enumerate(lines):
            if DEF_LINE_PATTERN.match(line):
                candidate_block = textwrap.dedent("\n".join(lines[idx:])).strip()
                try:
                    parsed = ast.parse(candidate_block)
                    if any(isinstance(n, ast.FunctionDef) for n in ast.walk(parsed)):
                        return True
                except SyntaxError:
                    # Try parsing just the def header + next indented lines
                    sub_lines = [line]
                    for follow in lines[idx + 1 :]:
                        if follow.startswith((" ", "\t")) or not follow.strip():
                            sub_lines.append(follow)
                        else:
                            break
                    if len([ln for ln in sub_lines if ln.strip()]) >= 2:
                        try:
                            parsed_sub = ast.parse(
                                textwrap.dedent("\n".join(sub_lines))
                            )
                            if any(
                                isinstance(n, ast.FunctionDef)
                                for n in ast.walk(parsed_sub)
                            ):
                                return True
                        except SyntaxError:
                            pass
    return False


def verify_code_turn(
    draft: NeuralSocraticDraft,
    problem_rules: dict[str, Any],
    iteration: int = 1,
    model_used: str = "gemini-3.1-flash-lite",
    student_raw_input: str | None = None,
    timeout_seconds: float = 2.0,
) -> tuple[SymbolicVerdict, bool]:
    """Run Step 2 deterministic AST + Sandbox verification on a NeuralSocraticDraft."""
    start_ts = time.perf_counter()
    chat_mode = bool(problem_rules.get("chat_mode", False))
    code_to_check = (student_raw_input or draft.student_symbolic_claim or "").strip()
    looks_like_code = "def " in code_to_check or "\n" in code_to_check

    required_nodes = list(problem_rules.get("required_ast_nodes", []))
    forbidden_nodes = list(problem_rules.get("forbidden_ast_nodes", []))
    forbidden_calls = list(problem_rules.get("forbidden_calls", []))
    function_name = str(problem_rules.get("function_name", "")).strip()
    test_cases = list(problem_rules.get("test_cases", []))

    # Freeform chat with natural-language questions (no code submitted yet).
    if chat_mode and not looks_like_code and not test_cases:
        elapsed_ms = round((time.perf_counter() - start_ts) * 1000.0, 2)
        answer_leaked = detect_code_leak_in_hint(draft.socratic_question)
        if answer_leaked:
            return (
                SymbolicVerdict(
                    iteration=iteration,
                    passed=False,
                    student_step_correct=False,
                    answer_leaked_in_hint=True,
                    rejection_reason=(
                        "LEAK VIOLATION: Your Socratic hint leaked code via a markdown "
                        "code block or function definition. Provide a conceptual question only."
                    ),
                    symbolic_rule_checked="Python AST Chat Coach (anti-leak)",
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
                        "Rule CHAT_GOAL violated: Cannot claim the coding goal is "
                        "reached without verified student code."
                    ),
                    symbolic_rule_checked="Python AST Chat Coach (open-ended)",
                    model_used=model_used,
                    latency_ms=elapsed_ms,
                ),
                False,
            )
        if not draft.socratic_question.strip():
            return (
                SymbolicVerdict(
                    iteration=iteration,
                    passed=False,
                    student_step_correct=False,
                    answer_leaked_in_hint=False,
                    rejection_reason="Rule CHAT_REPLY violated: Socratic reply was empty.",
                    symbolic_rule_checked="Python AST Chat Coach (open-ended)",
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
                symbolic_rule_checked="Python AST Chat Coach (open-ended)",
                model_used=model_used,
                latency_ms=elapsed_ms,
            ),
            False,
        )

    ast_ok, ast_err = inspect_ast_structure(
        code_str=code_to_check,
        required_ast_nodes=required_nodes,
        forbidden_ast_nodes=forbidden_nodes,
        forbidden_calls=forbidden_calls,
    )

    allow_exec = get_settings().enable_code_execution
    sandbox_ok = False
    verification_detail = ast_err or "AST_OK"
    if not allow_exec:
        # AST-only: never exec; structure (required/forbidden) defines solved.
        if ast_ok:
            verification_detail = "AST_OK_EXECUTION_DISABLED"
    elif ast_ok and test_cases:
        sandbox_ok, verification_detail = run_code_in_sandbox(
            code_str=code_to_check,
            function_name=function_name,
            test_cases=test_cases,
            timeout_seconds=timeout_seconds,
        )
    elif ast_ok and chat_mode and not test_cases:
        sandbox_ok = True
        verification_detail = "AST_OK_CHAT_NO_TESTS"

    if not allow_exec:
        student_step_correct = ast_ok
        problem_solved = bool(ast_ok)
    else:
        student_step_correct = bool(ast_ok and sandbox_ok)
        problem_solved = bool(ast_ok and sandbox_ok)

    # Always run anti-leak, even when the student step is already correct.
    answer_leaked = detect_code_leak_in_hint(draft.socratic_question)

    elapsed_ms = round((time.perf_counter() - start_ts) * 1000.0, 2)
    rule_label = (
        f"Python AST (EXECUTION_DISABLED) ({verification_detail})"
        if not allow_exec
        else f"Python AST & Sandbox ({verification_detail})"
    )

    if answer_leaked:
        return (
            SymbolicVerdict(
                iteration=iteration,
                passed=False,
                student_step_correct=student_step_correct,
                answer_leaked_in_hint=True,
                rejection_reason=(
                    "LEAK VIOLATION: Your Socratic hint leaked code via a markdown "
                    "code block or function definition. Provide a conceptual question only."
                ),
                symbolic_rule_checked="Python AST Anti-Leak Guard",
                model_used=model_used,
                latency_ms=elapsed_ms,
            ),
            False,
        )

    if draft.is_final_goal_reached_claim and not problem_solved:
        return (
            SymbolicVerdict(
                iteration=iteration,
                passed=False,
                student_step_correct=student_step_correct,
                answer_leaked_in_hint=False,
                rejection_reason=(
                    "Rule CODE_VERIFICATION violated: Draft claimed "
                    "is_final_goal_reached_claim=True, but code verification failed "
                    f"({verification_detail})."
                ),
                symbolic_rule_checked=rule_label,
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
            symbolic_rule_checked=rule_label,
            model_used=model_used,
            latency_ms=elapsed_ms,
        ),
        problem_solved,
    )
