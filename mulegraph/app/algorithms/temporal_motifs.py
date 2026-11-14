"""Temporal motif detection: suspicious *sequences* of transactions.

Implemented motifs
------------------
1. FAN_IN_THEN_FAN_OUT - many accounts pay one account, which then quickly
   distributes to many destinations.
2. RAPID_DISTRIBUTION  - a large inbound amount followed by outbound payments
   within a short grace period (pass-through behaviour).
3. SEQUENTIAL_CHAIN    - a -> b -> c -> (d) chain where each hop happens
   shortly after the previous one.
4. REPEATED_CIRCULAR   - the same directed loop observed repeatedly in the
   window (delegates to cycle detection).

All motifs are bounded: candidate selection is degree-ordered, every loop is
budgeted, and each motif carries transaction-level evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import GraphConfig
from ..graph.adjacency_index import Window
from ..graph.graph_store import GraphStore
from .common import Budget, Pattern, severity_for_score, stable_pattern_id
from .cycle_detection import find_cycles


@dataclass
class MotifParams:
    min_fan_in: int = 4
    min_fan_out: int = 4
    fan_window_seconds: float = 60.0
    distribution_grace_seconds: float = 120.0
    min_received_amount: float = 10_000.0
    pass_through_ratio: float = 0.6
    chain_length: int = 4
    max_hop_gap_seconds: float = 60.0
    max_candidates: int = 300
    max_motifs: int = 50

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class MotifScanResult:
    window: Window | None
    patterns: list[Pattern] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": None if self.window is None else self.window.to_dict(),
            "motif_count": len(self.patterns),
            "motifs": [p.to_dict() for p in self.patterns],
            "detection_parameters": self.parameters,
            "budget": self.budget,
        }


def _settled_in(store: GraphStore, account: str, window: Window | None) -> list[tuple[float, str, str, float]]:
    rows = []
    for ts, other, tx_id in store.index.in_neighbors(account, window):
        rec = store.transactions.get(tx_id)
        if rec is not None and rec.is_settled:
            rows.append((ts, other, tx_id, rec.amount))
    rows.sort(key=lambda r: r[0])
    return rows


def _settled_out(store: GraphStore, account: str, window: Window | None) -> list[tuple[float, str, str, float]]:
    rows = []
    for ts, other, tx_id in store.index.out_neighbors(account, window):
        rec = store.transactions.get(tx_id)
        if rec is not None and rec.is_settled:
            rows.append((ts, other, tx_id, rec.amount))
    rows.sort(key=lambda r: r[0])
    return rows


def detect_temporal_motifs(
    store: GraphStore,
    window: Window | None = None,
    params: MotifParams | None = None,
    config: GraphConfig | None = None,
    budget: Budget | None = None,
) -> MotifScanResult:
    """Run all motif detectors over one time window."""
    cfg = config or store.config
    params = params or MotifParams()
    budget = budget or Budget(max_visits=cfg.max_traversal_nodes)
    result = MotifScanResult(window=window, parameters=params.to_dict())

    candidates = [acc for acc, _ in store.index.top_accounts_by_degree(limit=params.max_candidates)]

    for account in candidates:
        if budget.exhausted or len(result.patterns) >= params.max_motifs:
            break
        if not budget.tick():
            break
        _fan_in_then_fan_out(store, account, window, params, result)
        _rapid_distribution(store, account, window, params, result)

    if not budget.exhausted and len(result.patterns) < params.max_motifs:
        _sequential_chains(store, window, params, budget, result)

    if not budget.exhausted and len(result.patterns) < params.max_motifs:
        _repeated_circular(store, window, cfg, budget, result)

    result.budget = budget.to_dict()
    return result


def _fan_in_then_fan_out(
    store: GraphStore,
    account: str,
    window: Window | None,
    params: MotifParams,
    result: MotifScanResult,
) -> None:
    """Many pay in within a short span, then the account pays many out."""
    incoming = _settled_in(store, account, window)
    if len(incoming) < params.min_fan_in:
        return

    # group inbound bursts
    for i, (ts0, _src0, _tx0, _amt0) in enumerate(incoming):
        burst = [
            row for row in incoming[i:]
            if row[0] - ts0 <= params.fan_window_seconds
        ]
        if len(burst) < params.min_fan_in:
            continue
        burst_sources = {row[1] for row in burst}
        if len(burst_sources) < params.min_fan_in:
            continue

        last_in_ts = max(row[0] for row in burst)
        outgoing = [
            row for row in _settled_out(store, account, window)
            if last_in_ts <= row[0] <= last_in_ts + params.distribution_grace_seconds
        ]
        out_destinations = {row[1] for row in outgoing}
        if len(outgoing) < params.min_fan_out or len(out_destinations) < params.min_fan_out:
            continue

        tx_ids = [row[2] for row in burst] + [row[2] for row in outgoing]
        if len(set(tx_ids)) != len(tx_ids):
            continue  # avoid re-reporting the same burst

        result.patterns.append(
            Pattern(
                pattern_type="FAN_IN_THEN_FAN_OUT",
                pattern_id=stable_pattern_id("FAN_IN_THEN_FAN_OUT", tx_ids),
                accounts_involved=[account, *sorted(burst_sources), *sorted(out_destinations)],
                transaction_ids=tx_ids,
                amounts=[row[3] for row in burst] + [row[3] for row in outgoing],
                timestamps=[row[0] for row in burst] + [row[0] for row in outgoing],
                window=window,
                algorithm="temporal_motifs.detect_fan_in_then_fan_out",
                metrics={
                    "inbound_accounts": len(burst_sources),
                    "inbound_transactions": len(burst),
                    "outbound_accounts": len(out_destinations),
                    "outbound_transactions": len(outgoing),
                    "inbound_amount": round(sum(r[3] for r in burst), 2),
                    "outbound_amount": round(sum(r[3] for r in outgoing), 2),
                    "burst_seconds": round(max(r[0] for r in burst) - ts0, 3),
                    "pass_through_seconds": round(
                        max(r[0] for r in outgoing) - last_in_ts, 3
                    ),
                },
                parameters=params.to_dict(),
                severity="HIGH",
                explanation=(
                    f"{len(burst_sources)} accounts paid into {account} within "
                    f"{round(max(r[0] for r in burst) - ts0, 1)}s and it distributed to "
                    f"{len(out_destinations)} destinations within "
                    f"{round(max(r[0] for r in outgoing) - last_in_ts, 1)}s."
                ),
            )
        )
        return  # one motif per account per scan


def _rapid_distribution(
    store: GraphStore,
    account: str,
    window: Window | None,
    params: MotifParams,
    result: MotifScanResult,
) -> None:
    """Large inbound amount followed by quick pass-through to others."""
    incoming = _settled_in(store, account, window)
    if not incoming:
        return
    for start_idx, (ts0, _src, _tx, _amt) in enumerate(incoming):
        inbound_window = [r for r in incoming[start_idx:] if r[0] - ts0 <= params.distribution_grace_seconds]
        received = sum(r[3] for r in inbound_window)
        if received < params.min_received_amount:
            continue
        outgoing = [
            r
            for r in _settled_out(store, account, window)
            if ts0 <= r[0] <= ts0 + params.distribution_grace_seconds
        ]
        distributed = sum(r[3] for r in outgoing)
        if distributed < params.pass_through_ratio * received or len(outgoing) < 2:
            continue
        tx_ids = [r[2] for r in inbound_window] + [r[2] for r in outgoing]
        if len(set(tx_ids)) != len(tx_ids):
            continue
        result.patterns.append(
            Pattern(
                pattern_type="RAPID_DISTRIBUTION",
                pattern_id=stable_pattern_id("RAPID_DISTRIBUTION", tx_ids),
                accounts_involved=sorted({r[1] for r in inbound_window} | {r[1] for r in outgoing} | {account}),
                transaction_ids=tx_ids,
                amounts=[r[3] for r in inbound_window] + [r[3] for r in outgoing],
                timestamps=[r[0] for r in inbound_window] + [r[0] for r in outgoing],
                window=window,
                algorithm="temporal_motifs.detect_rapid_distribution",
                metrics={
                    "received_amount": round(received, 2),
                    "distributed_amount": round(distributed, 2),
                    "pass_through_ratio": round(distributed / received, 3),
                    "inbound_transactions": len(inbound_window),
                    "outbound_transactions": len(outgoing),
                },
                parameters=params.to_dict(),
                severity="HIGH" if distributed / received >= 0.85 else "MEDIUM",
                explanation=(
                    f"{account} received {round(received, 2)} and forwarded "
                    f"{round(distributed, 2)} ({round(100 * distributed / received, 1)}%) "
                    f"within {params.distribution_grace_seconds:.0f}s."
                ),
            )
        )
        return


def _sequential_chains(
    store: GraphStore,
    window: Window | None,
    params: MotifParams,
    budget: Budget,
    result: MotifScanResult,
) -> None:
    """a -> b -> c -> d where each hop lands shortly after the previous."""
    target_len = max(3, params.chain_length)
    starts = [acc for acc, _ in store.index.top_accounts_by_degree(limit=params.max_candidates)]

    for start in starts:
        if budget.exhausted or len(result.patterns) >= params.max_motifs:
            return
        # DFS of depth target_len with hop-gap constraint
        def dfs(node: str, path: list[str], hops: list[tuple[str, str, str, float, float]]) -> None:
            if budget.exhausted or len(result.patterns) >= params.max_motifs:
                return
            if len(path) == target_len:
                tx_ids = [h[2] for h in hops]
                gaps = [hops[i + 1][4] - hops[i][4] for i in range(len(hops) - 1)]
                result.patterns.append(
                    Pattern(
                        pattern_type="SEQUENTIAL_CHAIN",
                        pattern_id=stable_pattern_id("SEQUENTIAL_CHAIN", tx_ids),
                        accounts_involved=list(path),
                        transaction_ids=tx_ids,
                        amounts=[h[3] for h in hops],
                        timestamps=[h[4] for h in hops],
                        window=window,
                        algorithm="temporal_motifs.detect_sequential_chain",
                        metrics={
                            "chain_length": len(path),
                            "max_hop_gap_seconds": round(max(gaps), 3) if gaps else 0.0,
                            "total_amount": round(sum(h[3] for h in hops), 2),
                        },
                        parameters=params.to_dict(),
                        severity="MEDIUM",
                        explanation=(
                            f"Sequential transfers {' -> '.join(path)} with each hop within "
                            f"{params.max_hop_gap_seconds:.0f}s of the previous one."
                        ),
                    )
                )
                return
            for _ts, nxt, tx_id in store.index.out_neighbors(node, window):
                if not budget.tick():
                    return
                if nxt in path:
                    continue
                rec = store.transactions.get(tx_id)
                if rec is None or not rec.is_settled:
                    continue
                if hops:
                    gap = _ts - hops[-1][4]
                    if gap < 0 or gap > params.max_hop_gap_seconds:
                        continue
                elif window is not None and _ts not in window:
                    continue
                dfs(
                    nxt,
                    path + [nxt],
                    hops + [(node, nxt, tx_id, rec.amount, _ts)],
                )

        dfs(start, [start], [])


def _repeated_circular(
    store: GraphStore,
    window: Window | None,
    cfg: GraphConfig,
    budget: Budget,
    result: MotifScanResult,
) -> None:
    scan = find_cycles(store, window=window, config=cfg, budget=budget)
    for group in scan.repeat_groups:
        result.patterns.append(
            Pattern(
                pattern_type="REPEATED_CIRCULAR",
                pattern_id=stable_pattern_id("REPEATED_CIRCULAR", group["transaction_ids"]),
                accounts_involved=group["accounts"],
                transaction_ids=group["transaction_ids"],
                amounts=[group["total_amount"]],
                timestamps=[],
                window=window,
                algorithm="temporal_motifs + cycle_detection.find_cycles",
                metrics={"occurrences": group["occurrences"]},
                parameters={"min_occurrences": 2},
                severity="HIGH" if group["occurrences"] >= 3 else "MEDIUM",
                explanation=(
                    f"Loop {' -> '.join(group['accounts'])} executed "
                    f"{group['occurrences']} times in the window."
                ),
            )
        )


def motifs_to_patterns(scan: MotifScanResult) -> list[Pattern]:
    return list(scan.patterns)
