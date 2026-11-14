"""Typed LangGraph investigation state (section 7).

Append-only fields use ``operator.add`` reducers so each node contributes a
delta; scalar fields are replaced by the returning node. The whole state is
plain JSON-serialisable data: it survives provider switches (the provider
manager is stateless w.r.t. investigations) and can be persisted for
long-running investigations.
"""

from __future__ import annotations

import operator
import time
import uuid
from typing import Annotated, Any, TypedDict


class InvestigationState(TypedDict, total=False):
    # identity / scope
    investigation_id: str
    use_case: str
    target_account_ids: Annotated[list[str], operator.add]
    target_transaction_ids: Annotated[list[str], operator.add]
    investigator_query: str
    investigation_objective: str
    time_window: str
    profile: str
    session_id: str | None

    # stages
    investigation_plan: dict[str, Any]
    initial_graph_evidence: Annotated[list[dict[str, Any]], operator.add]

    # collected evidence
    discovered_patterns: Annotated[list[dict[str, Any]], operator.add]
    investigated_accounts: Annotated[list[str], operator.add]
    transaction_paths: Annotated[list[dict[str, Any]], operator.add]
    tool_execution_history: Annotated[list[dict[str, Any]], operator.add]
    evidence_collection: Annotated[list[dict[str, Any]], operator.add]
    contradictions: Annotated[list[dict[str, Any]], operator.add]
    alternative_explanations: Annotated[list[dict[str, Any]], operator.add]
    missing_evidence: Annotated[list[dict[str, Any]], operator.add]

    # provider bookkeeping (preserved across switches)
    provider_used: str
    providers_used: Annotated[list[str], operator.add]
    fallback_history: Annotated[list[dict[str, Any]], operator.add]

    # control
    investigation_steps: int
    tool_call_count: int
    steps_without_new_evidence: int
    started_at: float
    deadline_at: float
    updated_at: float
    budget_exhausted: bool
    last_decision: str
    validation_notes: Annotated[list[str], operator.add]
    # per-investigation budget overrides (bounded autonomy)
    max_tool_calls_budget: int
    max_steps_budget: int

    # internal stage outputs (deterministic, consumed by later nodes)
    _observed_facts: list[dict[str, Any]]
    _detected_patterns: list[dict[str, Any]]
    _transaction_evidence: list[dict[str, Any]]
    _money_flow_paths: list[dict[str, Any]]
    _involved_accounts: list[dict[str, Any]]
    _evidence_strength: str
    _evidence_strength_basis: str
    _limitations: list[str]
    _alternatives: list[dict[str, Any]]
    _missing: list[dict[str, Any]]
    _base_next_steps: list[dict[str, Any]]
    _supporting_metrics: dict[str, Any]
    _correlation_notes: list[str]

    # outcome
    final_report: dict[str, Any] | None
    execution_status: str
    answer: str | None
    error: str | None


def new_investigation_state(
    *,
    investigation_id: str | None = None,
    account_ids: list[str] | None = None,
    transaction_ids: list[str] | None = None,
    question: str | None = None,
    objective: str | None = None,
    use_case: str = "auto",
    time_window: str = "24h",
    profile: str = "FAST",
    session_id: str | None = None,
    max_tool_calls: int = 25,
    max_wall_clock_s: float = 180.0,
    max_steps: int = 8,
) -> InvestigationState:
    """Fully populated initial state (every key present at invoke time)."""
    now = time.time()
    return InvestigationState(
        investigation_id=investigation_id or f"INV-{uuid.uuid4().hex[:12].upper()}",
        use_case=use_case,
        target_account_ids=list(account_ids or []),
        target_transaction_ids=list(transaction_ids or []),
        investigator_query=(question or "").strip(),
        investigation_objective=(objective or "").strip(),
        time_window=time_window,
        profile=profile,
        session_id=session_id,
        investigation_plan={},
        initial_graph_evidence=[],
        discovered_patterns=[],
        investigated_accounts=[],
        transaction_paths=[],
        tool_execution_history=[],
        evidence_collection=[],
        contradictions=[],
        alternative_explanations=[],
        missing_evidence=[],
        provider_used="",
        providers_used=[],
        fallback_history=[],
        investigation_steps=0,
        tool_call_count=0,
        steps_without_new_evidence=0,
        started_at=now,
        deadline_at=now + float(max_wall_clock_s),
        updated_at=now,
        budget_exhausted=False,
        last_decision="",
        validation_notes=[],
        final_report=None,
        execution_status="pending",
        answer=None,
        error=None,
        max_tool_calls_budget=int(max_tool_calls),
        max_steps_budget=int(max_steps),
        _observed_facts=[],
        _detected_patterns=[],
        _transaction_evidence=[],
        _money_flow_paths=[],
        _involved_accounts=[],
        _evidence_strength="insufficient",
        _evidence_strength_basis="",
        _limitations=[],
        _alternatives=[],
        _missing=[],
        _base_next_steps=[],
        _supporting_metrics={},
        _correlation_notes=[],
    )


__all__ = ["InvestigationState", "new_investigation_state"]
