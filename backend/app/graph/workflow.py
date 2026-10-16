"""LangGraph StateGraph builder & checkpointer orchestration (`document.md` Section 6)."""

from __future__ import annotations

from functools import partial
from typing import Any, Literal
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph

from backend.app.graph.nodes import (
    certified_output_node,
    circuit_breaker_node,
    ground_truth_node,
    neural_leap_node,
    route_after_interrogation,
    symbolic_interrogation_node,
)
from backend.app.graph.state import SocraticGraphState
from backend.app.schemas.socratic import SocraticTurnResponse, SymbolicVerdict
from backend.app.services.gemini_router import GeminiRouter

_memory_checkpointer = MemorySaver()


def get_postgres_checkpointer_cm(postgres_conn_str: str) -> Any:
    """Return an AsyncPostgresSaver context manager for Neon PostgreSQL checkpointing."""
    clean_url = postgres_conn_str.replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    return AsyncPostgresSaver.from_conn_string(clean_url)


def build_socratic_graph(
    router: GeminiRouter | None = None,
    checkpointer: Any | None = None,
) -> Any:
    """Construct and compile the 4-Step Neuro-Symbolic Socratic LangGraph StateGraph."""
    builder = StateGraph(SocraticGraphState)

    bound_neural_leap = (
        partial(neural_leap_node, router=router)
        if router is not None
        else neural_leap_node
    )

    builder.add_node("ground_truth_node", ground_truth_node)
    builder.add_node("neural_leap_node", bound_neural_leap)
    builder.add_node("symbolic_interrogation_node", symbolic_interrogation_node)
    builder.add_node("certified_output_node", certified_output_node)
    builder.add_node("circuit_breaker_node", circuit_breaker_node)

    builder.add_edge(START, "ground_truth_node")
    builder.add_edge("ground_truth_node", "neural_leap_node")
    builder.add_edge("neural_leap_node", "symbolic_interrogation_node")

    builder.add_conditional_edges(
        "symbolic_interrogation_node",
        route_after_interrogation,
        {
            "certified_output_node": "certified_output_node",
            "neural_leap_node": "neural_leap_node",
            "circuit_breaker_node": "circuit_breaker_node",
        },
    )

    builder.add_edge("certified_output_node", END)
    builder.add_edge("circuit_breaker_node", END)

    active_checkpointer = (
        _memory_checkpointer if checkpointer is None else checkpointer
    )
    return builder.compile(checkpointer=active_checkpointer)


async def execute_socratic_turn(
    session_id: str,
    track: Literal["MATH", "CODE", "RAG"],
    student_input: str,
    problem_payload: dict[str, Any] | None = None,
    retrieved_chunks: list[dict[str, Any]] | None = None,
    conversation_history: list[dict[str, str]] | None = None,
    router: GeminiRouter | None = None,
    checkpointer: Any | None = None,
) -> SocraticTurnResponse:
    """Execute a complete 4-Step Socratic Cycle turn and return a SocraticTurnResponse."""
    compiled_graph = build_socratic_graph(
        router=router,
        checkpointer=checkpointer,
    )

    initial_state: SocraticGraphState = {
        "session_id": session_id,
        "track": track,
        "problem_payload": problem_payload or {},
        "student_input": student_input,
        "conversation_history": conversation_history or [],
        "retrieved_chunks": retrieved_chunks or [],
        "iteration": 0,
        "latest_draft": None,
        "audit_trail": [],
        "final_reply": "",
        "problem_solved": False,
        "circuit_breaker_triggered": False,
    }

    config = {"configurable": {"thread_id": session_id}}
    final_state: SocraticGraphState = await compiled_graph.ainvoke(
        initial_state,
        config=config,
    )

    audit_verdicts = [
        SymbolicVerdict.model_validate(item)
        for item in final_state.get("audit_trail", [])
    ]

    return SocraticTurnResponse(
        session_id=session_id,
        track=track,
        socratic_reply=final_state.get("final_reply", ""),
        problem_solved=bool(final_state.get("problem_solved", False)),
        iterations_taken=int(final_state.get("iteration", len(audit_verdicts))),
        circuit_breaker_triggered=bool(
            final_state.get("circuit_breaker_triggered", False)
        ),
        audit_trail=audit_verdicts,
    )
