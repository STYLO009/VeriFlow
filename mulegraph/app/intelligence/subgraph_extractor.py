"""Subgraph extraction around a target account.

Produces a bounded, JSON-serialisable neighbourhood (nodes + individual
transaction edges) that an external AI system can consume without access to
the internal graph database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..graph.adjacency_index import Window
from ..graph.graph_store import GraphStore


@dataclass
class SubgraphView:
    root: str
    hops: int
    window: Window | None
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    node_count: int = 0
    edge_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "hops": self.hops,
            "window": None if self.window is None else self.window.to_dict(),
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "truncated": self.truncated,
            "nodes": self.nodes,
            "edges": self.edges,
        }


def extract_subgraph(
    store: GraphStore,
    account_id: str,
    hops: int = 1,
    window: Window | None = None,
    max_nodes: int = 300,
    max_edges: int = 1_000,
    settled_only: bool = False,
) -> SubgraphView:
    """Bounded BFS extraction of the neighbourhood around ``account_id``."""
    hops = max(1, hops)
    nodes, edge_rows = store.neighborhood(
        account_id, hops=hops, window=window, limit=max_nodes
    )

    view = SubgraphView(root=account_id, hops=hops, window=window)
    for node in sorted(nodes):
        data = store.graph.nodes.get(node, {})
        degrees = store.degrees(node, window)
        view.nodes.append(
            {
                "account_id": node,
                "first_seen": data.get("first_seen"),
                "last_seen": data.get("last_seen"),
                **degrees,
                "is_target": node == account_id,
            }
        )

    seen: set[str] = set()
    for src, dst, tx_id, ts in edge_rows:
        if tx_id in seen:
            continue
        record = store.transactions.get(tx_id)
        if record is None:
            continue
        if settled_only and not record.is_settled:
            continue
        seen.add(tx_id)
        if len(view.edges) >= max_edges:
            view.truncated = True
            break
        view.edges.append(
            {
                "transaction_id": tx_id,
                "source": src,
                "destination": dst,
                "amount": record.amount,
                "currency": record.currency,
                "timestamp": ts,
                "status": record.status.value,
                "settled": record.is_settled,
            }
        )

    view.edges.sort(key=lambda e: e["timestamp"])
    view.node_count = len(view.nodes)
    view.edge_count = len(view.edges)
    view.truncated = view.truncated or len(nodes) >= max_nodes
    return view
