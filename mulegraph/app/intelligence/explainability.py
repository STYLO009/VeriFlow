"""Evidence model and explainability helpers.

The evidence system deliberately separates three kinds of statements so a
downstream AI consumer can reason about them differently:

1. ``GRAPH_FACT``                - directly observed, never inferred
2. ``DETECTED_PATTERN``          - output of a named graph algorithm
3. ``RISK_INTERPRETATION``       - rule-based scoring / severity judgement

Nothing here invents transactions: every evidence item that references
transactions carries real transaction ids from the store.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..algorithms.common import Pattern
from ..graph.adjacency_index import Window
from ..graph.models import format_timestamp


class EvidenceKind(str, Enum):
    GRAPH_FACT = "GRAPH_FACT"
    DETECTED_PATTERN = "DETECTED_PATTERN"
    RISK_INTERPRETATION = "RISK_INTERPRETATION"


@dataclass
class EvidenceItem:
    kind: EvidenceKind
    label: str
    details: dict[str, Any]
    source_algorithm: str
    explanation: str
    transaction_ids: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "label": self.label,
            "details": self.details,
            "source_algorithm": self.source_algorithm,
            "explanation": self.explanation,
            "transaction_ids": self.transaction_ids,
            "parameters": self.parameters,
        }


def graph_fact(
    label: str,
    details: dict[str, Any],
    explanation: str,
    transaction_ids: list[str] | None = None,
    source: str = "graph_store",
) -> EvidenceItem:
    return EvidenceItem(
        kind=EvidenceKind.GRAPH_FACT,
        label=label,
        details=details,
        source_algorithm=source,
        explanation=explanation,
        transaction_ids=transaction_ids or [],
    )


def pattern_evidence(pattern: Pattern) -> EvidenceItem:
    data = pattern.to_dict()
    return EvidenceItem(
        kind=EvidenceKind.DETECTED_PATTERN,
        label=pattern.pattern_type,
        details={
            "pattern_id": pattern.pattern_id,
            "accounts_involved": pattern.accounts_involved,
            "amounts": pattern.amounts,
            "timestamps": pattern.timestamps,
            "time_window": data["time_window"],
            "supporting_metrics": pattern.metrics,
            "severity": pattern.severity,
        },
        source_algorithm=pattern.algorithm,
        explanation=pattern.explanation,
        transaction_ids=pattern.transaction_ids,
        parameters=pattern.parameters,
    )


def risk_interpretation(
    label: str,
    details: dict[str, Any],
    explanation: str,
    source: str = "risk_engine",
) -> EvidenceItem:
    return EvidenceItem(
        kind=EvidenceKind.RISK_INTERPRETATION,
        label=label,
        details=details,
        source_algorithm=source,
        explanation=explanation,
    )


def summarize_window(window: Window | None) -> dict[str, Any] | None:
    return None if window is None else window.to_dict()


def describe_transaction_ids(transaction_ids: list[str], limit: int = 20) -> str:
    if not transaction_ids:
        return "no transactions"
    shown = transaction_ids[:limit]
    suffix = f" (+{len(transaction_ids) - limit} more)" if len(transaction_ids) > limit else ""
    return ", ".join(shown) + suffix


def build_evidence_bundle(
    facts: list[EvidenceItem],
    patterns: list[Pattern],
    interpretations: list[EvidenceItem],
    anchor: str,
) -> list[dict[str, Any]]:
    """Merge the three evidence streams in a stable, readable order."""
    bundle: list[dict[str, Any]] = []
    for item in facts:
        bundle.append(item.to_dict())
    for pattern in patterns:
        bundle.append(pattern_evidence(pattern).to_dict())
    for item in interpretations:
        bundle.append(item.to_dict())
    for idx, entry in enumerate(bundle, start=1):
        entry["evidence_id"] = f"EV-{anchor}-{idx:03d}"
    return bundle


def evidence_digest(evidence: list[dict[str, Any]]) -> str:
    """Deterministic digest so consumers can detect changed analyses."""
    keys = [
        f"{e.get('kind')}:{e.get('label')}:{','.join(e.get('transaction_ids', []))}"
        for e in evidence
    ]
    return hashlib.sha1("|".join(keys).encode("utf-8")).hexdigest()[:12]


def render_timeline(transaction_ids: list[str], lookup: dict[str, Any]) -> str:
    """Human-readable chronological timeline from real transaction records."""
    rows = []
    for tx_id in transaction_ids:
        rec = lookup.get(tx_id)
        if rec is None:
            continue
        rows.append(
            f"{format_timestamp(rec.created_at)} {rec.source_account} -> "
            f"{rec.destination_account} {rec.amount} [{rec.status.value}] ({tx_id})"
        )
    return "\n".join(sorted(rows))
