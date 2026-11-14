"""Directed circular-transaction (cycle) detection.

Requirements handled here:

* configurable cycle lengths (``min_length`` .. ``max_length``)
* every cycle edge carries its transaction id, amount and timestamp
* repeated circular activity inside a time window is counted
* traversal is depth-bounded and budget-limited (no infinite loops)
* duplicate cycles are removed by canonical rotation normalisation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import GraphConfig
from ..graph.adjacency_index import Window
from ..graph.graph_store import GraphStore
from .common import Budget, Pattern, severity_for_score, stable_pattern_id


@dataclass
class CycleEvidence:
    """One concrete circular flow with transaction-level evidence."""

    accounts: list[str]  # closed loop, e.g. [A, B, C] (A->B->C->A)
    transaction_ids: list[str]
    amounts: list[float]
    timestamps: list[float]
    length: int

    @property
    def total_amount(self) -> float:
        return round(sum(self.amounts), 2)

    @property
    def duration(self) -> float:
        return round(max(self.timestamps) - min(self.timestamps), 3) if self.timestamps else 0.0

    @property
    def fingerprint(self) -> tuple[str, ...]:
        """Rotation-invariant identity used for de-duplication."""
        return canonical_cycle(self.accounts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accounts": self.accounts,
            "transaction_ids": self.transaction_ids,
            "amounts": self.amounts,
            "timestamps": self.timestamps,
            "length": self.length,
            "total_amount": self.total_amount,
            "duration_seconds": self.duration,
        }


def canonical_cycle(accounts: list[str]) -> tuple[str, ...]:
    """Rotate a cycle so it starts at its smallest node (dedupe key)."""
    if not accounts:
        return tuple()
    idx = min(range(len(accounts)), key=lambda i: accounts[i])
    return tuple(accounts[idx:] + accounts[:idx])


@dataclass
class CycleScanResult:
    window: Window | None
    cycles: list[CycleEvidence] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    repeat_groups: list[dict[str, Any]] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.cycles)

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": None if self.window is None else self.window.to_dict(),
            "cycle_count": self.count,
            "cycles": [c.to_dict() for c in self.cycles],
            "repeated_activity": self.repeat_groups,
            "detection_parameters": self.parameters,
            "budget": self.budget,
        }


def _pick_edge(
    store: GraphStore,
    src: str,
    dst: str,
    window: Window | None,
) -> tuple[str, float, float] | None:
    """Earliest settled transaction src -> dst inside the window."""
    for ts, _other, tx_id in store.index.edges_between(src, dst, window):
        record = store.transactions.get(tx_id)
        if record is not None and record.is_settled:
            return tx_id, ts, record.amount
    return None


def find_cycles(
    store: GraphStore,
    window: Window | None = None,
    min_length: int = 3,
    max_length: int | None = None,
    max_cycles: int | None = None,
    config: GraphConfig | None = None,
    budget: Budget | None = None,
) -> CycleScanResult:
    """Find directed cycles of settled transactions within length bounds.

    Uses canonical-start depth-limited DFS: a cycle is only explored from its
    lexicographically smallest account, which removes duplicate reporting while
    still discovering every distinct loop.
    """
    cfg = config or store.config
    min_length = max(2, min_length)
    max_length = max_length or cfg.max_cycle_length
    max_cycles = max_cycles or cfg.max_cycles
    budget = budget or Budget(max_visits=cfg.max_traversal_nodes)

    params = {
        "min_length": min_length,
        "max_length": max_length,
        "max_cycles": max_cycles,
        "settled_only": True,
    }
    result = CycleScanResult(window=window, parameters=params)
    if max_length < min_length:
        return result

    found: dict[tuple[tuple[str, ...], frozenset[str]], CycleEvidence] = {}
    # Candidate starts: only accounts that can be the canonical minimum.
    starts = sorted(store.index.accounts())

    for start in starts:
        if len(found) >= max_cycles or budget.exhausted:
            break
        path: list[str] = [start]
        on_path: set[str] = {start}
        edges: list[tuple[str, float, float]] = []  # (tx_id, ts, amount) per hop

        def walk(node: str) -> None:
            if budget.exhausted or len(found) >= max_cycles:
                return
            depth = len(path)
            if depth > max_length:
                return
            for _ts, nxt, _tx in store.index.out_neighbors(node, window):
                if not budget.tick():
                    return
                if nxt < start:
                    continue  # cycle would be canonical elsewhere
                if nxt == start:
                    if depth >= min_length:
                        _record_cycle(found, path, edges, nxt, store, window, max_cycles)
                    continue
                if nxt in on_path:
                    continue  # simple cycles only - no repeated nodes
                if depth + 1 > max_length:
                    continue
                edge = _pick_edge(store, node, nxt, window)
                if edge is None:
                    continue
                path.append(nxt)
                on_path.add(nxt)
                edges.append(edge)
                walk(nxt)
                edges.pop()
                path.pop()
                on_path.discard(nxt)
                if budget.exhausted or len(found) >= max_cycles:
                    return

        walk(start)

    result.cycles = list(found.values())
    result.cycles.sort(key=lambda c: (c.length, c.total_amount), reverse=True)
    result.budget = budget.to_dict()
    result.repeat_groups = _repeated_activity(result.cycles, store, window)
    return result


def _record_cycle(
    found: dict[tuple[tuple[str, ...], frozenset[str]], CycleEvidence],
    path: list[str],
    edges: list[tuple[str, float, float]],
    start: str,
    store: GraphStore,
    window: Window | None,
    max_cycles: int,
) -> None:
    accounts = list(path)  # start -> ... -> last
    # closing edge last -> start
    closing = _pick_edge(store, accounts[-1], start, window)
    if closing is None:
        return
    full_accounts = list(path)  # loop nodes without duplicating the start node
    all_edges = edges + [closing]
    fingerprint = canonical_cycle(full_accounts)
    tx_ids = [e[0] for e in all_edges]
    # dedupe by (loop, edge-set): the same loop executed with different
    # transactions is a legitimate *repeated* occurrence, not a duplicate
    key = (fingerprint, frozenset(tx_ids))
    if key in found or len(found) >= max_cycles:
        return
    if any(set(c.transaction_ids) == set(tx_ids) for c in found.values()):
        return
    found[key] = CycleEvidence(
        accounts=full_accounts,
        transaction_ids=tx_ids,
        amounts=[e[2] for e in all_edges],
        timestamps=[e[1] for e in all_edges],
        length=len(full_accounts),
    )


def _repeated_activity(
    cycles: list[CycleEvidence],
    store: GraphStore,
    window: Window | None,
) -> list[dict[str, Any]]:
    """Estimate repeated executions of each detected account loop.

    A cycle discovered once still counts as *repeated* when its hops carry
    multiple distinct settled transactions inside the window: the loop cannot
    have executed more times than its least-used hop, so
    ``occurrences = min(edges per hop)`` is a safe lower bound.
    """
    representatives: dict[tuple[str, ...], CycleEvidence] = {}
    for cycle in cycles:
        representatives.setdefault(cycle.fingerprint, cycle)

    repeated: list[dict[str, Any]] = []
    for fingerprint, cycle in representatives.items():
        accounts = list(fingerprint)
        length = len(accounts)
        if length < 2:
            continue
        hop_pairs = [(accounts[i], accounts[(i + 1) % length]) for i in range(length)]
        per_hop_counts: list[int] = []
        hop_tx: list[list[str]] = []
        for src, dst in hop_pairs:
            txs = [
                tx
                for _ts, _other, tx in store.index.edges_between(src, dst, window)
                if (rec := store.transactions.get(tx)) is not None and rec.is_settled
            ]
            per_hop_counts.append(len(txs))
            hop_tx.append(txs)

        if not per_hop_counts or min(per_hop_counts) < 2:
            continue

        occurrences = min(per_hop_counts)
        all_tx = sorted({tx for group in hop_tx for tx in group})
        total_amount = round(
            sum(
                store.transactions[tx].amount
                for tx in all_tx
                if tx in store.transactions
            ),
            2,
        )
        repeated.append(
            {
                "accounts": list(fingerprint),
                "occurrences": occurrences,
                "transaction_ids": all_tx,
                "total_amount": total_amount,
                "edges_per_hop": per_hop_counts,
            }
        )
    repeated.sort(key=lambda g: g["occurrences"], reverse=True)
    return repeated


def cycles_to_patterns(scan: CycleScanResult) -> list[Pattern]:
    """Turn cycle findings into explainable Pattern evidence."""
    patterns: list[Pattern] = []
    for cycle in scan.cycles:
        patterns.append(
            Pattern(
                pattern_type="CIRCULAR_TRANSACTION",
                pattern_id=stable_pattern_id("CIRCULAR_TRANSACTION", cycle.transaction_ids),
                accounts_involved=cycle.accounts,
                transaction_ids=cycle.transaction_ids,
                amounts=cycle.amounts,
                timestamps=cycle.timestamps,
                window=scan.window,
                algorithm="cycle_detection.find_cycles",
                metrics={
                    "cycle_length": cycle.length,
                    "total_amount": cycle.total_amount,
                    "duration_seconds": cycle.duration,
                },
                parameters=scan.parameters,
                severity=severity_for_score(min(1.0, 0.3 + cycle.length / 12)),
                explanation=(
                    f"Funds moved in a closed loop: "
                    f"{' -> '.join(cycle.accounts + [cycle.accounts[0]])} across "
                    f"{cycle.length} settled transactions totalling {cycle.total_amount}."
                ),
            )
        )
    for group in scan.repeat_groups:
        patterns.append(
            Pattern(
                pattern_type="REPEATED_CIRCULAR_ACTIVITY",
                pattern_id=stable_pattern_id("REPEATED_CIRCULAR", group["transaction_ids"]),
                accounts_involved=group["accounts"],
                transaction_ids=group["transaction_ids"],
                amounts=[group["total_amount"]],
                timestamps=[],
                window=scan.window,
                algorithm="cycle_detection.find_cycles",
                metrics={"occurrences": group["occurrences"]},
                parameters=scan.parameters,
                severity="HIGH" if group["occurrences"] >= 3 else "MEDIUM",
                explanation=(
                    f"The same account loop {' -> '.join(group['accounts'])} recurred "
                    f"{group['occurrences']} times inside the analysed window."
                ),
            )
        )
    return patterns
