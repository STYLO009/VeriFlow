"""Transparent, rule-based graph risk engine.

IMPORTANT: this is *not* a machine-learning classifier. It is a deterministic
scoring function over already-detected graph patterns. Every contribution to
the final score is listed with its weight so an analyst (or downstream AI)
can audit exactly why a severity was assigned.

The score is an investigative triage signal - never a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..algorithms.common import Pattern, severity_for_score
from ..algorithms.fan_detection import FanResult
from ..graph.graph_store import GraphStore
from .explainability import EvidenceItem, risk_interpretation

# Explicit, auditable signal weights (sum to 1.0).
SIGNAL_WEIGHTS: dict[str, float] = {
    "fan_in": 0.22,
    "fan_out": 0.22,
    "circular_transactions": 0.18,
    "repeated_circular": 0.08,
    "temporal_motifs": 0.14,
    "risk_propagation": 0.08,
    "community_concentration": 0.05,
    "centrality_bridge": 0.03,
}


@dataclass
class Signal:
    name: str
    value: float  # normalised 0..1
    weight: float
    observed: dict[str, Any] = field(default_factory=dict)

    @property
    def contribution(self) -> float:
        return round(self.value * self.weight, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.name,
            "value": round(self.value, 3),
            "weight": self.weight,
            "contribution": self.contribution,
            "observed": self.observed,
        }


@dataclass
class RiskAssessment:
    account_id: str
    score: float
    severity: str
    signals: list[Signal] = field(default_factory=list)
    explanations: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "score": round(self.score, 4),
            "severity": self.severity,
            "signals": [s.to_dict() for s in self.signals],
            "signal_weights": SIGNAL_WEIGHTS,
            "explanations": self.explanations,
            "scoring_parameters": self.parameters,
            "disclaimer": (
                "Rule-based graph triage score derived from observed transaction "
                "patterns. It is not a legal or behavioural verdict and connection "
                "to flagged accounts alone is not proof of wrongdoing."
            ),
        }


def assess(
    account_id: str,
    store: GraphStore,
    fan_in: FanResult | None = None,
    fan_out: FanResult | None = None,
    patterns: list[Pattern] | None = None,
    propagation_score: float | None = None,
    community_suspicious: bool = False,
    is_bridge: bool = False,
) -> RiskAssessment:
    """Combine detected graph signals into one auditable triage score."""
    patterns = patterns or []
    assessment = RiskAssessment(
        account_id=account_id,
        score=0.0,
        severity="LOW",
        parameters={"signal_weights": SIGNAL_WEIGHTS},
    )

    if fan_in is not None:
        value = min(1.0, fan_in.score) if fan_in.detected else min(0.5, fan_in.score)
        assessment.signals.append(
            Signal(
                name="fan_in",
                value=value,
                weight=SIGNAL_WEIGHTS["fan_in"],
                observed={
                    "unique_incoming_accounts": fan_in.unique_accounts,
                    "incoming_transactions": fan_in.transaction_count,
                    "total_amount": fan_in.total_amount,
                },
            )
        )
        if fan_in.detected:
            assessment.explanations.append(
                f"Fan-in detected: {fan_in.unique_accounts} unique sources, "
                f"{fan_in.transaction_count} settled transactions."
            )

    if fan_out is not None:
        value = min(1.0, fan_out.score) if fan_out.detected else min(0.5, fan_out.score)
        assessment.signals.append(
            Signal(
                name="fan_out",
                value=value,
                weight=SIGNAL_WEIGHTS["fan_out"],
                observed={
                    "unique_outgoing_accounts": fan_out.unique_accounts,
                    "outgoing_transactions": fan_out.transaction_count,
                    "total_amount": fan_out.total_amount,
                },
            )
        )
        if fan_out.detected:
            assessment.explanations.append(
                f"Fan-out detected: {fan_out.unique_accounts} unique destinations."
            )

    circular = [p for p in patterns if p.pattern_type == "CIRCULAR_TRANSACTION"]
    repeated = [p for p in patterns if p.pattern_type in ("REPEATED_CIRCULAR", "REPEATED_CIRCULAR_ACTIVITY")]
    motifs = [
        p
        for p in patterns
        if p.pattern_type in ("FAN_IN_THEN_FAN_OUT", "RAPID_DISTRIBUTION", "SEQUENTIAL_CHAIN")
    ]

    if circular:
        involved = sum(1 for p in circular if account_id in p.accounts_involved)
        assessment.signals.append(
            Signal(
                name="circular_transactions",
                value=min(1.0, involved / 2),
                weight=SIGNAL_WEIGHTS["circular_transactions"],
                observed={"cycles_involving_account": involved, "cycles_total": len(circular)},
            )
        )
        assessment.explanations.append(
            f"Account participates in {involved} detected transaction cycle(s)."
        )

    if repeated:
        occurrences = max((p.metrics.get("occurrences", 1) for p in repeated), default=1)
        assessment.signals.append(
            Signal(
                name="repeated_circular",
                value=min(1.0, occurrences / 4),
                weight=SIGNAL_WEIGHTS["repeated_circular"],
                observed={"max_occurrences": occurrences},
            )
        )
        assessment.explanations.append(
            f"Repeated circular activity observed (up to {occurrences} occurrences)."
        )

    if motifs:
        involved = sum(1 for p in motifs if account_id in p.accounts_involved)
        assessment.signals.append(
            Signal(
                name="temporal_motifs",
                value=min(1.0, involved / 2),
                weight=SIGNAL_WEIGHTS["temporal_motifs"],
                observed={"motifs_involving_account": involved},
            )
        )
        assessment.explanations.append(
            f"{involved} temporal motif(s) link this account to rapid pass-through behaviour."
        )

    if propagation_score is not None and propagation_score > 0:
        assessment.signals.append(
            Signal(
                name="risk_propagation",
                value=min(1.0, propagation_score),
                weight=SIGNAL_WEIGHTS["risk_propagation"],
                observed={"propagated_score": round(propagation_score, 3)},
            )
        )
        assessment.explanations.append(
            "Account is connected to a flagged account; association alone is a "
            "review lead, not proof."
        )

    if community_suspicious:
        assessment.signals.append(
            Signal(
                name="community_concentration",
                value=1.0,
                weight=SIGNAL_WEIGHTS["community_concentration"],
                observed={"suspicious_community": True},
            )
        )
        assessment.explanations.append(
            "Account belongs to a tightly concentrated transaction community."
        )

    if is_bridge:
        assessment.signals.append(
            Signal(
                name="centrality_bridge",
                value=1.0,
                weight=SIGNAL_WEIGHTS["centrality_bridge"],
                observed={"bridge_node": True},
            )
        )
        assessment.explanations.append(
            "Account bridges otherwise separate transaction groups."
        )

    score = sum(s.contribution for s in assessment.signals)
    assessment.score = min(1.0, score)
    assessment.severity = severity_for_score(assessment.score)
    if not assessment.explanations:
        assessment.explanations.append("No elevated graph signals detected for this account.")
    return assessment


def assessment_evidence(assessment: RiskAssessment) -> EvidenceItem:
    return risk_interpretation(
        label="GRAPH_RISK_SCORE",
        details={
            "account_id": assessment.account_id,
            "score": round(assessment.score, 4),
            "severity": assessment.severity,
            "signals": [s.to_dict() for s in assessment.signals],
        },
        explanation="; ".join(assessment.explanations),
    )
