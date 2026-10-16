"""Deterministic Symbolic Verifiers package (SymPy, Python AST, RAG Quote Guard)."""

from backend.app.symbolic.ast_verifier import (
    detect_code_leak_in_hint,
    inspect_ast_structure,
    run_code_in_sandbox,
    verify_code_turn,
)
from backend.app.symbolic.math_verifier import (
    detect_math_answer_leak,
    expressions_are_equivalent,
    parse_math_expression,
    verify_math_turn,
)
from backend.app.symbolic.rag_verifier import (
    detect_rag_answer_span_leak,
    normalize_whitespace_case,
    verify_rag_turn,
    verify_verbatim_citation,
)

__all__ = [
    "parse_math_expression",
    "expressions_are_equivalent",
    "detect_math_answer_leak",
    "verify_math_turn",
    "inspect_ast_structure",
    "detect_code_leak_in_hint",
    "run_code_in_sandbox",
    "verify_code_turn",
    "normalize_whitespace_case",
    "verify_verbatim_citation",
    "detect_rag_answer_span_leak",
    "verify_rag_turn",
]
