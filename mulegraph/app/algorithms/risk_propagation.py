"""Transparent graph-based risk propagation.

Given a set of *already flagged* accounts (seeds), risk spreads through the
transaction graph with:

* configurable propagation depth (hard stop - no unlimited propagation)
* exponential decay by hop distance
* explainable propagation paths (which seed, through which route)
* an explicit ``association_only`` marker: being connected to a flagged
  account is a lead for investigation, never proof of wrongdoing

This is a deterministic graph algorithm - no machine learning involved.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..config import GraphConfig
from ..graph.adjacency_index import Window
from ..graph.graph_store import GraphStore
from .common import Budget, severity_for_score


@dataclass
class PropagationHop:
    account: str
    transaction_id: str
    timestamp: float
    direction: str  # "out" = seed paid this account, "in" = this account paid the seed

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "transaction_id": self.transaction_id,
            "timestamp": self.timestamp,
            "direction": self.direction,
        }


@dataclass
class RiskNode:
    account_id: str
    risk_score: float
    distance_hops: int
    seed_account: str | None
    seed_score: float
    path: list[PropagationHop] = field(default_factory=list)
    association_only: bool = True
    severity: str = "LOW"
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "risk_score": round(self.risk_score, 4),
            "distance_hops": self.distance_hops,
            "seed_account": self.seed_account,
            "seed_score": round(self.seed_score, 4),
            "path": [h.to_dict() for h in self.path],
            "association_only": self.association_only,
            "severity": self.severity,
            "explanation": self.explanation,
        }


@dataclass
class PropagationResult:
    seeds: dict[str, float]
    window: Window | None
    nodes: list[RiskNode] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seeds": self.seeds,
            "window": None if self.window is None else self.window.to_dict(),
            "propagated_accounts": len(self.nodes),
            "nodes": [n.to_dict() for n in self.nodes],
            "detection_parameters": self.parameters,
            "budget": self.budget,
        }


def propagate_risk(
    store: GraphStore,
    seeds: dict[str, float],
    window: Window | None = None,
    depth: int | None = None,
    decay: float | None = None,
    config: GraphConfig | None = None,
    max_accounts: int = 500,
    budget: Budget | None = None,
) -> PropagationResult:
    """Spread seed risk scores through bounded, decaying graph traversal."""
    cfg = config or store.config
    depth = max(0, depth if depth is not None else cfg.propagation_depth)
    decay = decay if decay is not None else cfg.propagation_decay
    decay = min(max(decay, 0.0), 1.0)
    budget = budget or Budget(max_visits=cfg.max_traversal_nodes)

    params = {"depth": depth, "decay": decay, "max_accounts": max_accounts, "settled_only": True}
    result = PropagationResult(seeds=dict(seeds), window=window, parameters=params)
    if not seeds or depth == 0:
        result.budget = budget.to_dict()
        return result

    best: dict[str, RiskNode] = {}
    # BFS layers keep hop distance exact and prevent unbounded propagation.
    # tuple: (account, hop, decayed_score, seed, seed_score, path)
    frontier: deque[tuple[str, int, float, str, float, list[PropagationHop]]] = deque()
    for seed, score in seeds.items():
        if not store.has_account(seed):
            continue
        frontier.append((seed, 0, float(score), seed, float(score), []))
        best[seed] = RiskNode(
            account_id=seed,
            risk_score=float(score),
            distance_hops=0,
            seed_account=seed,
            seed_score=float(score),
            path=[],
            association_only=False,
            severity=severity_for_score(float(score)),
            explanation=(
                f"Account was directly flagged with risk score {round(score, 3)} "
                f"before propagation."
            ),
        )

    while frontier:
        if budget.exhausted or len(best) >= max_accounts:
            break
        current, hop, score, seed, seed_score, path = frontier.popleft()
        if hop >= depth:
            continue

        for direction in ("out", "in"):
            entries = (
                store.index.out_neighbors(current, window)
                if direction == "out"
                else store.index.in_neighbors(current, window)
            )
            for ts, other, tx_id in entries:
                if not budget.tick():
                    break
                new_hop = PropagationHop(
                    account=other, transaction_id=tx_id, timestamp=ts, direction=direction
                )
                improved = _relax(
                    best,
                    other,
                    hop + 1,
                    score * decay,
                    seed,
                    seed_score,
                    path,
                    new_hop,
                    max_accounts,
                )
                if improved and hop + 1 < depth:
                    frontier.append(
                        (other, hop + 1, score * decay, seed, seed_score, path + [new_hop])
                    )

    nodes = [n for n in best.values() if n.distance_hops > 0]
    nodes.sort(key=lambda n: (n.risk_score, -n.distance_hops), reverse=True)
    result.nodes = nodes
    result.budget = budget.to_dict()
    return result


def _relax(
    best: dict[str, RiskNode],
    account: str,
    hop: int,
    score: float,
    seed: str,
    seed_score: float,
    path: list[PropagationHop],
    new_hop: PropagationHop,
    max_accounts: int,
) -> bool:
    """Update the best known risk for ``account``. Returns True if improved."""
    existing = best.get(account)
    if existing is not None and existing.distance_hops < hop:
        return False  # deeper path to an already better-known node
    if existing is not None and existing.risk_score >= score:
        return False  # no improvement
    if len(best) >= max_accounts and existing is None:
        return False

    new_path = path + [new_hop]
    explanation = (
        f"{account} is {hop} hop(s) from flagged account {seed} "
        f"(seed score {round(seed_score, 3)}, decayed to {round(score, 3)} at distance {hop}). "
        f"Connection alone is a lead for review - not proof of wrongdoing."
    )
    best[account] = RiskNode(
        account_id=account,
        risk_score=max(0.0, score),
        distance_hops=hop,
        seed_account=seed,
        seed_score=round(seed_score, 4),
        path=new_path,
        association_only=True,
        severity=severity_for_score(max(0.0, score)),
        explanation=explanation,
    )
    return True


def seeds_from_patterns(
    patterns: list[Any],
    seed_score: float = 0.9,
) -> dict[str, float]:
    """Derive propagation seeds from high-severity detected patterns.

    Only HIGH/CRITICAL pattern accounts become seeds - keeps propagation
    anchored in observed evidence instead of guesswork.
    """
    seeds: dict[str, float] = {}
    for pattern in patterns:
        severity = getattr(pattern, "severity", None)
        if severity not in ("HIGH", "CRITICAL"):
            continue
        for account in getattr(pattern, "accounts_involved", []) or []:
            seeds[account] = max(seeds.get(account, 0.0), seed_score)
    return seeds
