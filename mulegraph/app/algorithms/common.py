"""Shared building blocks for graph algorithms.

Every algorithm:

* accepts a :class:`GraphStore`, an optional :class:`Window` and a
  :class:`Budget` so expensive work can be bounded / interrupted
* returns plain dataclasses that serialise to JSON without further mapping
* records the parameters it used so results are reproducible and explainable
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from typing import Any

from ..graph.adjacency_index import Window
from ..graph.graph_store import GraphStore


@dataclass
class Budget:
    """Execution budget: wall-clock deadline + node-visit allowance."""

    deadline: float | None = None  # epoch seconds
    max_visits: int = 20_000
    visits: int = 0
    exhausted_reason: str | None = None

    @classmethod
    def with_timeout_ms(cls, timeout_ms: float | None, max_visits: int = 20_000) -> "Budget":
        if timeout_ms is None or timeout_ms <= 0:
            return cls(deadline=None, max_visits=max_visits)
        return cls(deadline=time.time() + timeout_ms / 1000.0, max_visits=max_visits)

    def tick(self, visits: int = 1) -> bool:
        """Record work; returns False when the budget is exhausted."""
        self.visits += visits
        if self.visits > self.max_visits:
            self.exhausted_reason = "max_visits"
            return False
        if self.deadline is not None and time.time() > self.deadline:
            self.exhausted_reason = "timeout"
            return False
        return True

    @property
    def remaining_ms(self) -> float | None:
        if self.deadline is None:
            return None
        return max(0.0, (self.deadline - time.time()) * 1000.0)

    @property
    def exhausted(self) -> bool:
        return self.exhausted_reason is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "visits": self.visits,
            "exhausted": self.exhausted,
            "exhausted_reason": self.exhausted_reason,
            "remaining_ms": None if self.remaining_ms is None else round(self.remaining_ms, 2),
        }


def stable_pattern_id(pattern_type: str, keys: list[str]) -> str:
    """Deterministic, human-readable pattern id (reproducible across runs)."""
    digest = hashlib.sha1("|".join(sorted(keys)).encode("utf-8")).hexdigest()[:10]
    return f"{pattern_type}:{digest}"


@dataclass
class Pattern:
    """A detected graph pattern with full transaction-level evidence."""

    pattern_type: str
    pattern_id: str
    accounts_involved: list[str]
    transaction_ids: list[str]
    amounts: list[float]
    timestamps: list[float]
    window: Window | None
    algorithm: str
    metrics: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    severity: str = "MEDIUM"
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_type": self.pattern_type,
            "pattern_id": self.pattern_id,
            "accounts_involved": self.accounts_involved,
            "transaction_ids": self.transaction_ids,
            "amounts": self.amounts,
            "timestamps": self.timestamps,
            "time_window": None if self.window is None else self.window.to_dict(),
            "algorithm": self.algorithm,
            "supporting_metrics": self.metrics,
            "detection_parameters": self.parameters,
            "severity": self.severity,
            "explanation": self.explanation,
        }


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / len(values))


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * (p / 100.0)
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return ordered[int(k)]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def time_concentration(timestamps: list[float], bucket_seconds: float = 60.0) -> dict[str, Any]:
    """How clustered transaction timestamps are inside the window.

    Returns peak bucket count, peak share of all transactions and the span.
    """
    if not timestamps:
        return {
            "span_seconds": 0.0,
            "peak_bucket_seconds": bucket_seconds,
            "peak_bucket_count": 0,
            "peak_share": 0.0,
            "frequency_per_second": 0.0,
        }
    ordered = sorted(timestamps)
    span = ordered[-1] - ordered[0]
    buckets: dict[int, int] = {}
    for ts in ordered:
        key = int(ts // bucket_seconds)
        buckets[key] = buckets.get(key, 0) + 1
    peak = max(buckets.values())
    return {
        "span_seconds": round(span, 3),
        "peak_bucket_seconds": bucket_seconds,
        "peak_bucket_count": peak,
        "peak_share": round(peak / len(ordered), 3),
        "frequency_per_second": round(len(ordered) / span, 4) if span > 0 else None,
    }


def amount_distribution(amounts: list[float]) -> dict[str, Any]:
    if not amounts:
        return {"count": 0, "total": 0.0}
    m = mean(amounts)
    sd = stdev(amounts)
    return {
        "count": len(amounts),
        "total": round(sum(amounts), 2),
        "min": round(min(amounts), 2),
        "max": round(max(amounts), 2),
        "mean": round(m, 2),
        "stdev": round(sd, 2),
        "coefficient_of_variation": round(sd / m, 3) if m else None,
    }


def severity_for_score(score: float) -> str:
    """Map a normalised 0..1 score to a severity band.

    Bands are calibrated against the signal weights in ``risk_engine``: one
    fully-detected primary signal (fan-in / fan-out / cycle) reaches MEDIUM,
    two strong signals reach HIGH, and a broad combination reaches CRITICAL.
    """
    if score >= 0.6:
        return "CRITICAL"
    if score >= 0.35:
        return "HIGH"
    if score >= 0.15:
        return "MEDIUM"
    return "LOW"


def window_dict(window: Window | None) -> dict[str, Any] | None:
    return None if window is None else window.to_dict()


def require_store(store: GraphStore | None) -> GraphStore:
    if store is None:
        raise ValueError("GraphStore is required")
    return store
