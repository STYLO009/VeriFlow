"""Centrality analysis for the transaction graph.

Implemented metrics
-------------------
* in-degree / out-degree / weighted degree
* PageRank (directed, weighted by settled transaction count)
* betweenness centrality (exact for small graphs, sampled for large ones so
  runtime stays bounded on streaming workloads)
* bridge-node identification (articulation points of the undirected view,
  limited to a configurable candidate budget)

Expensive metrics are meant to be cached by the analyzer and refreshed in a
background thread - never recomputed per transaction.
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

logger = logging.getLogger("mulegraph.centrality")


def pagerank_power_iteration(
    graph: nx.Graph,
    alpha: float = 0.85,
    max_iter: int = 100,
    tol: float = 1.0e-8,
    weight: str = "weight",
) -> dict[str, float]:
    """Dependency-free PageRank (pure Python power iteration).

    Used as a fallback when ``nx.pagerank`` is unavailable (networkx requires
    scipy for it). Deterministic: uniform initial ranks, dangling mass
    redistributed uniformly.
    """
    nodes = list(graph.nodes())
    n = len(nodes)
    if n == 0:
        return {}
    if n == 1:
        return {nodes[0]: 1.0}

    out_weight: dict[str, float] = {}
    edges: list[tuple[str, str, float]] = []
    for u, v, data in graph.edges(data=True):
        w = float(data.get(weight, 1.0) or 1.0)
        if w <= 0:
            continue
        edges.append((u, v, w))
        out_weight[u] = out_weight.get(u, 0.0) + w

    rank: dict[str, float] = {node: 1.0 / n for node in nodes}
    for _ in range(max_iter):
        dangling = sum(rank[node] for node in nodes if out_weight.get(node, 0.0) == 0.0)
        base = (1.0 - alpha) / n + alpha * dangling / n
        new_rank: dict[str, float] = {node: base for node in nodes}
        for u, v, w in edges:
            new_rank[v] += alpha * rank[u] * (w / out_weight[u])
        diff = sum(abs(new_rank[node] - rank[node]) for node in nodes)
        rank = new_rank
        if diff < tol:
            break
    total = sum(rank.values()) or 1.0
    return {node: value / total for node, value in rank.items()}


@dataclass
class CentralityScanResult:
    window: Window | None
    metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    bridge_nodes: list[str] = field(default_factory=list)
    top_pagerank: list[dict[str, Any]] = field(default_factory=list)
    top_betweenness: list[dict[str, Any]] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)

    def for_account(self, account_id: str) -> dict[str, float]:
        return self.metrics.get(account_id, {})

    def to_dict(self, include_all: bool = False) -> dict[str, Any]:
        return {
            "window": None if self.window is None else self.window.to_dict(),
            "parameters": self.parameters,
            "accounts_measured": len(self.metrics),
            "bridge_nodes": self.bridge_nodes,
            "top_pagerank": self.top_pagerank,
            "top_betweenness": self.top_betweenness,
            "metrics": self.metrics if include_all else dict(list(self.metrics.items())[:100]),
            "budget": self.budget,
        }


def compute_centrality(
    store: GraphStore,
    window: Window | None = None,
    config: GraphConfig | None = None,
    max_nodes: int = 5_000,
    betweenness_sample: int = 64,
    compute_betweenness: bool = True,
    compute_pagerank: bool = True,
    budget: Budget | None = None,
) -> CentralityScanResult:
    """Compute centrality metrics over the settled-transaction window graph."""
    cfg = config or store.config
    budget = budget or Budget(max_visits=cfg.max_traversal_nodes)
    params = {
        "max_nodes": max_nodes,
        "betweenness_sample": betweenness_sample,
        "settled_only": True,
        "weighted": True,
    }
    result = CentralityScanResult(window=window, parameters=params)

    directed = store.windowed_graph(window, settled_only=True) if window else store.graph
    if directed.number_of_nodes() == 0:
        result.budget = budget.to_dict()
        return result

    # Degree metrics come straight from the index (cheap, exact).
    degrees: dict[str, dict[str, float]] = {}
    for account in directed.nodes():
        if not budget.tick():
            break
        in_deg = store.index.degree_in(account, window)
        out_deg = store.index.degree_out(account, window)
        weighted = 0.0
        for _ts, other, tx_id in store.index.in_neighbors(account, window):
            rec = store.transactions.get(tx_id)
            if rec is not None and rec.is_settled:
                weighted += rec.amount
        for _ts, other, tx_id in store.index.out_neighbors(account, window):
            rec = store.transactions.get(tx_id)
            if rec is not None and rec.is_settled:
                weighted += rec.amount
        degrees[account] = {
            "in_degree": float(in_deg),
            "out_degree": float(out_deg),
            "weighted_degree": round(weighted, 2),
        }
    result.metrics = degrees

    # Bound the expensive part to the busiest subgraph.
    if directed.number_of_nodes() > max_nodes:
        ranked = sorted(directed.degree(), key=lambda kv: kv[1], reverse=True)[:max_nodes]
        keep = {n for n, _ in ranked}
        directed = directed.subgraph(keep).copy()
        logger.info("centrality computed on bounded subgraph of %d nodes", len(keep))

    undirected = directed.to_undirected(as_view=True)

    if compute_pagerank and directed.number_of_edges() > 0 and budget.tick():
        try:
            ranks = nx.pagerank(directed, weight="weight", max_iter=60, tol=1.0e-6)
        except Exception as exc:  # networkx needs scipy for pagerank
            logger.debug("nx.pagerank unavailable (%s); using pure-python power iteration", exc)
            ranks = pagerank_power_iteration(directed, weight="weight")
        for account, value in ranks.items():
            result.metrics.setdefault(account, {})["pagerank"] = round(value, 8)

    if compute_betweenness and directed.number_of_edges() > 0 and budget.tick():
        sample = min(betweenness_sample, directed.number_of_nodes())
        try:
            # k-sample keeps this practical at 50-100 TPS streaming volumes
            values = nx.betweenness_centrality(
                directed, k=sample if sample < directed.number_of_nodes() else None,
                weight=None, seed=42,
            )
            for account, value in values.items():
                result.metrics.setdefault(account, {})["betweenness"] = round(value, 8)
        except Exception as exc:  # pragma: no cover
            logger.warning("betweenness failed: %s", exc)

    # Bridge nodes: articulation points of the undirected settled graph.
    if undirected.number_of_nodes() > 0 and budget.tick():
        try:
            components = list(nx.connected_components(undirected))
            # articulation points only meaningful inside sizeable components
            bridges: list[str] = []
            for component in components:
                if len(component) < 4:
                    continue
                sub = undirected.subgraph(component)
                bridges.extend(nx.articulation_points(sub))
            result.bridge_nodes = sorted(bridges)[:100]
        except Exception as exc:  # pragma: no cover
            logger.warning("bridge analysis failed: %s", exc)

    result.top_pagerank = _top(result.metrics, "pagerank", 10)
    result.top_betweenness = _top(result.metrics, "betweenness", 10)
    result.budget = budget.to_dict()
    return result


def _top(metrics: dict[str, dict[str, float]], key: str, n: int) -> list[dict[str, Any]]:
    rows = [
        {"account_id": acc, key: values[key]}
        for acc, values in metrics.items()
        if key in values
    ]
    rows.sort(key=lambda r: r[key], reverse=True)
    return rows[:n]
