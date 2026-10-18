"""Shared normalization, structuring, summarization, and evidence-review core."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.graph.nodes import (
    generate_summary,
    map_evidence,
    sanitize_input,
    structure_session,
    verify_evidence_deterministically,
)
from app.schemas.note import SessionInput


class SummaryExecutionMode(str, Enum):
    PUBLIC_QUICK = "public_quick"
    AUTHENTICATED_FULL = "authenticated_full"


@dataclass(frozen=True)
class SummaryCorePolicy:
    mode: SummaryExecutionMode
    allow_retrieval_context: bool
    allow_persistence: bool
    deterministic_verification: bool


PUBLIC_QUICK_POLICY = SummaryCorePolicy(
    mode=SummaryExecutionMode.PUBLIC_QUICK,
    allow_retrieval_context=False,
    allow_persistence=False,
    deterministic_verification=True,
)

AUTHENTICATED_FULL_POLICY = SummaryCorePolicy(
    mode=SummaryExecutionMode.AUTHENTICATED_FULL,
    allow_retrieval_context=True,
    allow_persistence=True,
    deterministic_verification=True,
)

_RETRIEVAL_STATE_KEYS = {
    "retrieved_case_context",
    "retrieved_case_memory_chunks",
    "retrieved_authoritative_kb_chunks",
    "retrieved_template_context",
    "retrieved_privacy_context",
    "raw_regions_by_need",
    "grounding_context",
}


def run_summary_core(
    state: dict[str, Any],
    *,
    policy: SummaryCorePolicy,
) -> dict[str, Any]:
    """Run the shared AI core without retrieval, persistence, or document transforms.

    The caller selects an immutable request policy. Public requests fail closed if
    authenticated context or persistence accidentally enters their state.
    """
    session_input: SessionInput = state["session_input"]
    _validate_policy_boundary(state, session_input, policy)

    working_state = dict(state)
    updates: dict[str, Any] = {}
    if "sanitized_input" not in working_state:
        _apply_step(working_state, updates, sanitize_input)
    _apply_step(working_state, updates, structure_session)
    _apply_step(working_state, updates, map_evidence)
    _apply_step(working_state, updates, generate_summary)
    if policy.deterministic_verification:
        verification_updates = verify_evidence_deterministically(working_state)
        working_state.update(verification_updates)
        updates["session_summary_draft"] = verification_updates["session_summary_draft"]
        if policy.mode == SummaryExecutionMode.PUBLIC_QUICK:
            updates["verification_report"] = verification_updates["verification_report"]
        else:
            updates["core_verification_report"] = verification_updates["verification_report"]
    return updates


def summary_core_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node for the authenticated Full Session Summary workflow."""
    return run_summary_core(state, policy=AUTHENTICATED_FULL_POLICY)


def _apply_step(
    working_state: dict[str, Any],
    updates: dict[str, Any],
    step,
) -> None:
    step_updates = step(working_state)
    working_state.update(step_updates)
    updates.update(step_updates)


def _validate_policy_boundary(
    state: dict[str, Any],
    session_input: SessionInput,
    policy: SummaryCorePolicy,
) -> None:
    if session_input.persist and not policy.allow_persistence:
        raise ValueError("Public summary execution cannot persist counseling data.")
    if policy.allow_retrieval_context:
        return
    populated_context = [key for key in _RETRIEVAL_STATE_KEYS if state.get(key)]
    if populated_context:
        raise ValueError("Public summary execution cannot use authenticated retrieval context.")
    if state.get("actor"):
        raise ValueError("Public summary execution cannot use an authenticated actor.")
    if session_input.previous_session_summary.strip():
        raise ValueError("Public summary execution cannot load previous-session context.")
