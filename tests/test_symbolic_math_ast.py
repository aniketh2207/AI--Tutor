"""Phase 2 Verification Suite: Symbolic Math (`SymPy`) & Code (`Python AST` + Sandbox) Verifiers."""

from __future__ import annotations

import time
from backend.app.schemas.socratic import NeuralSocraticDraft
from backend.app.symbolic.ast_verifier import (
    detect_code_leak_in_hint,
    inspect_ast_structure,
    run_code_in_sandbox,
    verify_code_turn,
)
from backend.app.symbolic.math_verifier import (
     verify_math_turn,
)

MATH_PROBLEM_RULES = {
    "variables": ["x"],
    "target_expr": "3*x**2 + 2",
    "allowed_intermediate_exprs": ["3*x**2", "2", "x**3", "2*x"],
}

CODE_PROBLEM_RULES = {
    "function_name": "sum_elements",
    "required_ast_nodes": ["FunctionDef", "For", "Return"],
    "forbidden_ast_nodes": ["While"],
    "forbidden_calls": ["sum"],
    "test_cases": [
        {"input": [[1, 2, 3, 4]], "expected": 10},
        {"input": [[-5, 5, 12]], "expected": 12},
        {"input": [[]], "expected": 0},
    ],
}


def test_math_verifier_valid_intermediate_and_final_steps() -> None:
    """Verify valid intermediate steps and algebraically equivalent final answers pass."""
    intermediate_draft = NeuralSocraticDraft(
        student_intent_summary="Student correctly differentiated x**3 to 3*x**2.",
        student_symbolic_claim="3*x**2",
        is_final_goal_reached_claim=False,
        socratic_question=(
            "You correctly found that the derivative of x**3 is 3*x**2. "
            "Now, what is the derivative of the linear term 2*x?"
        ),
    )
    verdict, solved = verify_math_turn(
        draft=intermediate_draft,
        problem_rules=MATH_PROBLEM_RULES,
        iteration=1,
    )
    assert verdict.passed is True
    assert verdict.student_step_correct is True
    assert verdict.answer_leaked_in_hint is False
    assert verdict.rejection_reason is None
    assert solved is False

    # Student reaches final answer using alternative algebraic form (2 + 3x^2)
    final_draft = NeuralSocraticDraft(
        student_intent_summary="Student combined both terms to reach the final derivative.",
        student_symbolic_claim="2 + 3x^2",
        is_final_goal_reached_claim=True,
        socratic_question="Spot on! You combined both derivatives to get 3*x**2 + 2.",
    )
    final_verdict, final_solved = verify_math_turn(
        draft=final_draft,
        problem_rules=MATH_PROBLEM_RULES,
        iteration=1,
    )
    assert final_verdict.passed is True
    assert final_verdict.student_step_correct is True
    assert final_verdict.answer_leaked_in_hint is False
    assert final_solved is True


def test_math_verifier_rejects_leaked_final_answer_in_hint() -> None:
    """Verify Socratic hints leaking the final answer (verbatim or symbolic) fail verification."""
    # 1. Verbatim string leak
    leaked_draft_verbatim = NeuralSocraticDraft(
        student_intent_summary="Student only differentiated the first term.",
        student_symbolic_claim="3*x**2",
        is_final_goal_reached_claim=False,
        socratic_question=(
            "Good start! Add the derivative of 2*x so your final answer is 3*x**2 + 2."
        ),
    )
    verdict_1, solved_1 = verify_math_turn(
        draft=leaked_draft_verbatim,
        problem_rules=MATH_PROBLEM_RULES,
        iteration=1,
    )
    assert verdict_1.passed is False
    assert verdict_1.answer_leaked_in_hint is True
    assert solved_1 is False
    assert verdict_1.rejection_reason is not None
    assert "LEAK VIOLATION" in verdict_1.rejection_reason

    # 2. Algebraically equivalent leak in backticks (`2 + 3*x^2`)
    leaked_draft_symbolic = NeuralSocraticDraft(
        student_intent_summary="Student is stuck on the second term.",
        student_symbolic_claim="3*x**2",
        is_final_goal_reached_claim=False,
        socratic_question="Hint: check if your expression simplifies to `2 + 3*x^2`.",
    )
    verdict_2, solved_2 = verify_math_turn(
        draft=leaked_draft_symbolic,
        problem_rules=MATH_PROBLEM_RULES,
        iteration=2,
    )
    assert verdict_2.passed is False
    assert verdict_2.answer_leaked_in_hint is True
    assert solved_2 is False
    assert verdict_2.rejection_reason is not None
    assert "LEAK VIOLATION" in verdict_2.rejection_reason


def test_math_verifier_rejects_false_final_goal_claim() -> None:
    """Verify draft claiming is_final_goal_reached_claim=True on partial work is rejected."""
    false_claim_draft = NeuralSocraticDraft(
        student_intent_summary="Student wrote 3*x**2.",
        student_symbolic_claim="3*x**2",
        is_final_goal_reached_claim=True,
        socratic_question="Congratulations, you solved the entire problem!",
    )
    verdict, solved = verify_math_turn(
        draft=false_claim_draft,
        problem_rules=MATH_PROBLEM_RULES,
        iteration=1,
    )
    assert verdict.passed is False
    assert solved is False
    assert verdict.rejection_reason is not None
    assert "GOAL_EQUIVALENCE" in verdict.rejection_reason


def test_ast_verifier_valid_and_invalid_structures() -> None:
    """Verify Python AST node inspection for required/forbidden nodes and forbidden calls."""
    valid_code = (
        "def sum_elements(nums):\n"
        "    total = 0\n"
        "    for x in nums:\n"
        "        total += x\n"
        "    return total\n"
    )
    ok, err = inspect_ast_structure(
        valid_code,
        required_ast_nodes=["FunctionDef", "For", "Return"],
        forbidden_ast_nodes=["While"],
        forbidden_calls=["sum"],
    )
    assert ok is True
    assert err is None

    # Full turn verification with valid code
    valid_draft = NeuralSocraticDraft(
        student_intent_summary="Student implemented iterative sum with a for loop.",
        student_symbolic_claim=valid_code,
        is_final_goal_reached_claim=True,
        socratic_question="Excellent work! Your loop handles empty lists and negative integers.",
    )
    verdict, solved = verify_code_turn(
        draft=valid_draft,
        problem_rules=CODE_PROBLEM_RULES,
        student_raw_input=valid_code,
    )
    assert verdict.passed is True
    assert verdict.student_step_correct is True
    assert solved is True

    # Forbidden While node
    while_code = (
        "def sum_elements(nums):\n"
        "    i = 0\n"
        "    while i < len(nums):\n"
        "        i += 1\n"
        "    return i\n"
    )
    ok_while, err_while = inspect_ast_structure(
        while_code,
        required_ast_nodes=["FunctionDef", "Return"],
        forbidden_ast_nodes=["While"],
        forbidden_calls=["sum"],
    )
    assert ok_while is False
    assert err_while is not None
    assert "AST_FORBIDDEN_NODE" in err_while

    # Forbidden built-in sum() call
    sum_call_code = (
        "def sum_elements(nums):\n"
        "    for _ in nums:\n"
        "        pass\n"
        "    return sum(nums)\n"
    )
    ok_call, err_call = inspect_ast_structure(
        sum_call_code,
        required_ast_nodes=["FunctionDef", "For", "Return"],
        forbidden_ast_nodes=["While"],
        forbidden_calls=["sum"],
    )
    assert ok_call is False
    assert err_call is not None
    assert "AST_FORBIDDEN_CALL" in err_call

    # Missing required For loop
    missing_for_code = "def sum_elements(nums):\n    return 0\n"
    ok_missing, err_missing = inspect_ast_structure(
        missing_for_code,
        required_ast_nodes=["FunctionDef", "For", "Return"],
    )
    assert ok_missing is False
    assert err_missing is not None
    assert "AST_MISSING_NODE" in err_missing


def test_ast_verifier_infinite_loop_timeout_within_2_5_seconds() -> None:
    """Verify `while True: pass` infinite loop is terminated by sandbox in <= 2.5 seconds."""
    infinite_loop_code = (
        "def sum_elements(nums):\n"
        "    while True:\n"
        "        pass\n"
        "    return 0\n"
    )
    start_ts = time.perf_counter()
    passed, detail = run_code_in_sandbox(
        code_str=infinite_loop_code,
        function_name="sum_elements",
        test_cases=[{"input": [[1, 2, 3]], "expected": 6}],
        timeout_seconds=2.0,
    )
    elapsed = time.perf_counter() - start_ts

    assert passed is False
    assert "SANDBOX_TIMEOUT" in detail
    assert elapsed <= 2.5, f"Sandbox took {elapsed:.2f}s, exceeding 2.5s limit!"


def test_ast_verifier_rejects_code_block_and_function_def_leaks() -> None:
    """Verify markdown code blocks and multi-line FunctionDef in hints are rejected."""
    incomplete_student_code = "def sum_elements(nums):\n    total = 0\n"

    # 1. Markdown ```python code fence leak
    fenced_leak_draft = NeuralSocraticDraft(
        student_intent_summary="Student only initialized total.",
        student_symbolic_claim=incomplete_student_code,
        is_final_goal_reached_claim=False,
        socratic_question=(
            "Try completing your function like this:\n"
            "```python\n"
            "def sum_elements(nums):\n"
            "    total = 0\n"
            "    for n in nums:\n"
            "        total += n\n"
            "    return total\n"
            "```"
        ),
    )
    verdict_fence, solved_fence = verify_code_turn(
        draft=fenced_leak_draft,
        problem_rules=CODE_PROBLEM_RULES,
        student_raw_input=incomplete_student_code,
    )
    assert verdict_fence.passed is False
    assert verdict_fence.answer_leaked_in_hint is True
    assert solved_fence is False
    assert verdict_fence.rejection_reason is not None
    assert "LEAK VIOLATION" in verdict_fence.rejection_reason

    # 2. Unfenced multi-line function definition leak
    raw_fn_hint = (
        "Consider writing:\n"
        "def sum_elements(nums):\n"
        "    return 0\n"
    )
    assert detect_code_leak_in_hint(raw_fn_hint) is True
