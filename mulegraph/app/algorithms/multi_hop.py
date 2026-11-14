"""Bounded multi-hop money-flow tracing.

Features
--------
* source -> destination tracing with configurable maximum hops
* time-window filtering (every hop must fall inside the window)
* per-hop and cumulative amount filtering
* shortest-path mode and all-paths mode (budget-limited)
* chronological transaction ordering along the reported flow
* full transaction-level evidence for every hop
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..config import GraphConfig
from ..graph.adjacency_index import Window
from ..graph.graph_store import GraphStore
from .common import Budget


@dataclass
class FlowHop:
    position: int
    from_account: str
    to_account: str
    transaction_id: str
    timestamp: float
    amount: float
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "from_account": self.from_account,
            "to_account": self.to_account,
            "transaction_id": self.transaction_id,
            "timestamp": self.timestamp,
            "amount": self.amount,
            "status": self.status,
        }


@dataclass
class MoneyFlowPath:
    source: str
    destination: str
    hops: list[FlowHop]
    hop_count: int
    chronological: bool

    @property
    def transaction_ids(self) -> list[str]:
        return [h.transaction_id for h in self.hops]

    @property
    def accounts(self) -> list[str]:
        if not self.hops:
            return []
        route = [self.hops[0].from_account]
        route.extend(h.to_account for h in self.hops)
        return route

    @property
    def total_amount(self) -> float:
        return round(sum(h.amount for h in self.hops), 2)

    @property
    def min_hop_amount(self) -> float:
        return round(min((h.amount for h in self.hops), default=0.0), 2)

    @property
    def duration(self) -> float:
        if not self.hops:
            return 0.0
        return round(max(h.timestamp for h in self.hops) - min(h.timestamp for h in self.hops), 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "destination": self.destination,
            "hop_count": self.hop_count,
            "accounts": self.accounts,
            "transaction_ids": self.transaction_ids,
            "total_amount": self.total_amount,
            "min_hop_amount": self.min_hop_amount,
            "duration_seconds": self.duration,
            "chronologically_ordered": self.chronological,
            "hops": [h.to_dict() for h in self.hops],
        }


@dataclass
class TraceResult:
    source: str
    destination: str
    window: Window | None
    paths: list[MoneyFlowPath] = field(default_factory=list)
    shortest_hops: int | None = None
    truncated: bool = False
    parameters: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    explored_nodes: int = 0

    @property
    def path_count(self) -> int:
        return len(self.paths)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "destination": self.destination,
            "window": None if self.window is None else self.window.to_dict(),
            "path_count": len(self.paths),
            "shortest_hops": self.shortest_hops,
            "truncated": self.truncated,
            "paths": [p.to_dict() for p in self.paths],
            "detection_parameters": self.parameters,
            "budget": self.budget,
            "explored_nodes": self.explored_nodes,
        }


def trace_money_flow(
    store: GraphStore,
    source: str,
    destination: str,
    max_hops: int | None = None,
    window: Window | None = None,
    min_amount: float | None = None,
    max_paths: int | None = None,
    shortest_only: bool = False,
    strict_chronological: bool = False,
    config: GraphConfig | None = None,
    budget: Budget | None = None,
) -> TraceResult:
    """Trace settled money flow from ``source`` to ``destination``."""
    cfg = config or store.config
    max_hops = max(1, min(max_hops or cfg.max_hops, cfg.max_hops))
    max_paths = max(1, max_paths or cfg.max_paths)
    budget = budget or Budget(max_visits=cfg.max_traversal_nodes)

    params = {
        "max_hops": max_hops,
        "min_amount": min_amount,
        "max_paths": max_paths,
        "shortest_only": shortest_only,
        "strict_chronological": strict_chronological,
        "settled_only": True,
        "windowed": window is not None,
    }
    result = TraceResult(source=source, destination=destination, window=window, parameters=params)

    if source == destination:
        result.budget = budget.to_dict()
        return result
    if not store.has_account(source) or not store.has_account(destination):
        result.budget = budget.to_dict()
        return result

    # BFS over (account, hop depth) keeps this shortest-path-first and bounded.
    queue: deque[tuple[str, list[FlowHop]]] = deque([(source, [])])
    visited_depth: dict[str, int] = {source: 0}
    found: list[MoneyFlowPath] = []
    explored = 0

    while queue:
        if budget.exhausted or len(found) >= max_paths:
            result.truncated = True
            break
        current, hops = queue.popleft()
        depth = len(hops)
        if depth >= max_hops:
            continue

        last_ts = hops[-1].timestamp if hops else None
        cumulative_min = min((h.amount for h in hops), default=float("inf"))

        for ts, nxt, tx_id in store.index.out_neighbors(current, window):
            if not budget.tick():
                break
            if min_amount is not None:
                record_min = store.transactions.get(tx_id)
                if record_min is None or record_min.amount < min_amount:
                    continue
            if strict_chronological and last_ts is not None and ts < last_ts:
                continue  # flow must not travel backwards in time

            record = store.transactions.get(tx_id)
            if record is None or not record.is_settled:
                continue  # held / rejected / reversed never trace as money flow

            if min_amount is not None and cumulative_min < min_amount:
                pass  # already enforced per hop

            hop = FlowHop(
                position=depth + 1,
                from_account=current,
                to_account=nxt,
                transaction_id=tx_id,
                timestamp=ts,
                amount=record.amount,
                status=record.status.value,
            )
            new_hops = hops + [hop]

            if nxt == destination:
                path = MoneyFlowPath(
                    source=source,
                    destination=destination,
                    hops=new_hops,
                    hop_count=len(new_hops),
                    chronological=_is_chronological(new_hops),
                )
                found.append(path)
                if shortest_only:
                    queue.clear()
                    break
                continue

            next_depth = depth + 1
            known = visited_depth.get(nxt)
            if shortest_only:
                if known is not None and known <= next_depth:
                    continue
                visited_depth[nxt] = next_depth
            else:
                # allow multiple routes but never revisit a node inside one path
                path_nodes = {source} | {h.to_account for h in hops}
                if nxt in path_nodes:
                    continue
                visited_depth[nxt] = min(known, next_depth) if known is not None else next_depth

            explored += 1
            queue.append((nxt, new_hops))

    found.sort(key=lambda p: (p.hop_count, -p.min_hop_amount))
    result.paths = found[:max_paths]
    result.shortest_hops = result.paths[0].hop_count if result.paths else None
    result.explored_nodes = explored
    result.budget = budget.to_dict()
    if budget.exhausted:
        result.truncated = True
    return result


def _is_chronological(hops: list[FlowHop]) -> bool:
    return all(hops[i].timestamp <= hops[i + 1].timestamp for i in range(len(hops) - 1))


def trace_to_patterns(result: TraceResult) -> list[dict[str, Any]]:
    """Structured money-flow records for the AI-ready response."""
    return [p.to_dict() for p in result.paths]
