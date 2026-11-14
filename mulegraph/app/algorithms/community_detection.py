"""Community detection over the transaction graph.

Uses NetworkX's Louvain implementation (``nx.community.louvain_communities``)
on an undirected, weighted projection of the settled-transaction graph, then
enriches each community with:

* membership and size
* internal / external transaction counts and volumes
* connectivity (density vs. possible edges)
* repeated interactions (account pairs with >= 2 transactions)
* concentration of internal volume

Results are cached by the caller (see ``intelligence/graph_analyzer.py``) and
refreshed in a background thread - never recomputed per transaction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from ..config import GraphConfig
from ..graph.adjacency_index import Window
from ..graph.graph_store import GraphStore
from .common import Budget

logger = logging.getLogger("mulegraph.communities")


@dataclass
class CommunityResult:
    community_id: str
    members: list[str]
    size: int
    internal_transactions: int
    internal_volume: float
    external_transactions: int
    external_volume: float
    connectivity: float
    repeated_interactions: int
    concentration: float
    suspicious: bool
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "community_id": self.community_id,
            "members": self.members,
            "size": self.size,
            "internal_transactions": self.internal_transactions,
            "internal_volume": round(self.internal_volume, 2),
            "external_transactions": self.external_transactions,
            "external_volume": round(self.external_volume, 2),
            "connectivity": round(self.connectivity, 4),
            "repeated_interactions": self.repeated_interactions,
            "volume_concentration": round(self.concentration, 4),
            "suspicious_concentration": self.suspicious,
            **self.metrics,
        }


@dataclass
class CommunityScanResult:
    window: Window | None
    communities: list[CommunityResult] = field(default_factory=list)
    algorithm: str = "louvain"
    parameters: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": None if self.window is None else self.window.to_dict(),
            "algorithm": self.algorithm,
            "community_count": len(self.communities),
            "communities": [c.to_dict() for c in self.communities],
            "detection_parameters": self.parameters,
            "budget": self.budget,
        }


def _build_undirected(store: GraphStore, window: Window | None) -> nx.Graph:
    graph = nx.Graph()
    for ts, src, dst, tx_id in (
        store.index.edges_in_window(window) if window else store.index.iter_all_edges()
    ):
        rec = store.transactions.get(tx_id)
        if rec is None or not rec.is_settled:
            continue
        if graph.has_edge(src, dst):
            edge = graph[src][dst]
            edge["weight"] += 1
            edge["volume"] += rec.amount
            edge["tx_ids"].append(tx_id)
        else:
            graph.add_edge(src, dst, weight=1, volume=rec.amount, tx_ids=[tx_id])
    return graph


def detect_communities(
    store: GraphStore,
    window: Window | None = None,
    config: GraphConfig | None = None,
    resolution: float = 1.0,
    min_size: int = 3,
    seed: int = 42,
    budget: Budget | None = None,
) -> CommunityScanResult:
    """Detect account clusters with Louvain (deterministic with ``seed``)."""
    cfg = config or store.config
    budget = budget or Budget(max_visits=cfg.max_traversal_nodes)
    params = {"resolution": resolution, "min_size": min_size, "seed": seed, "settled_only": True}
    result = CommunityScanResult(window=window, parameters=params)

    graph = _build_undirected(store, window)
    if graph.number_of_nodes() < min_size or graph.number_of_edges() == 0:
        result.budget = budget.to_dict()
        return result

    try:
        communities = nx.community.louvain_communities(
            graph, weight="weight", resolution=resolution, seed=seed
        )
        result.algorithm = "louvain"
    except Exception as exc:  # pragma: no cover - fallback path
        logger.warning("louvain failed (%s); falling back to connected components", exc)
        communities = [set(c) for c in nx.connected_components(graph)]
        result.algorithm = "connected_components"

    # global edge bookkeeping for external volume
    edge_by_pair: dict[frozenset[str], tuple[int, float]] = {}
    for u, v, data in graph.edges(data=True):
        edge_by_pair[frozenset((u, v))] = (data["weight"], data["volume"])

    communities = [c for c in communities if len(c) >= min_size]
    communities.sort(key=len, reverse=True)

    for idx, members in enumerate(communities):
        if not budget.tick():
            break
        result.communities.append(
            _score_community(idx, set(members), graph, edge_by_pair, window)
        )

    result.budget = budget.to_dict()
    return result


def _score_community(
    idx: int,
    members: set[str],
    graph: nx.Graph,
    edge_by_pair: dict[frozenset[str], tuple[int, float]],
    window: Window | None,
) -> CommunityResult:
    internal_tx = 0
    internal_vol = 0.0
    repeated = 0
    pair_count = 0
    for u in members:
        for v in members:
            if u >= v:
                continue
            pair_count += 1
            data = graph.get_edge_data(u, v)
            if not data:
                continue
            internal_tx += data["weight"]
            internal_vol += data["volume"]
            if data["weight"] >= 2:
                repeated += 1

    external_tx = 0
    external_vol = 0.0
    member_volumes: dict[str, float] = {m: 0.0 for m in members}
    for u in members:
        for v in graph.neighbors(u):
            if v in members:
                member_volumes[u] += graph[u][v]["volume"] / 2.0
                continue
            data = graph[u][v]
            external_tx += data["weight"]
            external_vol += data["volume"]
            member_volumes[v] = member_volumes.get(v, 0.0) + data["volume"] / 2.0

    possible = pair_count
    connectivity = (2 * internal_tx / (len(members) * (len(members) - 1))) if len(members) > 1 else 0.0

    # Herfindahl-style concentration of internal volume across members
    total_member_vol = sum(member_volumes.values())
    concentration = 0.0
    if total_member_vol > 0:
        shares = [v / total_member_vol for v in member_volumes.values()]
        concentration = sum(s**2 for s in shares)

    total_vol = internal_vol + external_vol
    internal_share = (internal_vol / total_vol) if total_vol else 0.0

    suspicious = (
        len(members) >= 3
        and connectivity >= 0.4
        and internal_share >= 0.7
        and (repeated >= 2 or internal_vol > 0)
    )

    top_holder = max(member_volumes, key=member_volumes.get) if member_volumes else None
    return CommunityResult(
        community_id=f"COMM-{idx + 1:03d}",
        members=sorted(members),
        size=len(members),
        internal_transactions=internal_tx,
        internal_volume=internal_vol,
        external_transactions=external_tx,
        external_volume=external_vol,
        connectivity=connectivity,
        repeated_interactions=repeated,
        concentration=concentration,
        suspicious=suspicious,
        metrics={
            "internal_volume_share": round(internal_share, 4),
            "largest_member_by_volume": top_holder,
            "window": None if window is None else window.to_dict(),
        },
    )


def community_for_account(scan: CommunityScanResult, account_id: str) -> CommunityResult | None:
    for community in scan.communities:
        if account_id in community.members:
            return community
    return None
