"""Community detection and centrality tests."""

from __future__ import annotations

import networkx as nx
import pytest

from app.algorithms.centrality import compute_centrality
from app.algorithms.community_detection import community_for_account, detect_communities
from app.graph.adjacency_index import Window
from app.graph.graph_store import GraphStore

from .conftest import T0, ingest, make_event

WINDOW = Window.between(T0 - 60, T0 + 900)


def _two_community_store(store: GraphStore) -> GraphStore:
    """Two dense clusters (4 accounts each) joined by one bridge edge."""
    events = []
    # cluster 1: fully connected with repeated transactions
    c1 = ["C1-A", "C1-B", "C1-C", "C1-D"]
    for i, src in enumerate(c1):
        for j, dst in enumerate(c1):
            if src != dst:
                events.append(make_event(f"K1-{i}{j}", src, dst, 500, T0 + (i + j)))
    # cluster 2
    c2 = ["C2-A", "C2-B", "C2-C", "C2-D"]
    for i, src in enumerate(c2):
        for j, dst in enumerate(c2):
            if src != dst:
                events.append(make_event(f"K2-{i}{j}", src, dst, 500, T0 + (i + j) + 5))
    # bridge between clusters
    events.append(make_event("BR-1", "C1-A", "C2-A", 10_000, T0 + 50))
    return ingest(store, events)


def test_communities_detected(store: GraphStore) -> None:
    _two_community_store(store)
    scan = detect_communities(store, window=WINDOW, min_size=3, seed=42)
    assert scan.algorithm == "louvain"
    assert len(scan.communities) >= 2
    membership = {m for c in scan.communities for m in c.members}
    assert "C1-A" in membership and "C2-D" in membership
    # each community reports internal/external volume
    for community in scan.communities:
        assert community.size >= 3
        assert community.internal_transactions > 0
        assert community.connectivity >= 0.0
        payload = community.to_dict()
        assert payload["community_id"].startswith("COMM-")


def test_communities_deterministic_with_seed(store: GraphStore) -> None:
    _two_community_store(store)
    first = detect_communities(store, window=WINDOW, seed=42)
    second = detect_communities(store, window=WINDOW, seed=42)
    assert [c.members for c in first.communities] == [c.members for c in second.communities]


def test_community_lookup(store: GraphStore) -> None:
    _two_community_store(store)
    scan = detect_communities(store, window=WINDOW, seed=42)
    found = community_for_account(scan, "C1-B")
    assert found is not None
    assert "C1-B" in found.members
    assert community_for_account(scan, "UNKNOWN-ACCOUNT") is None


def test_empty_graph_communities(store: GraphStore) -> None:
    scan = detect_communities(store, window=WINDOW)
    assert scan.communities == []


def test_small_graph_fallback(store: GraphStore) -> None:
    ingest(store, [make_event("SM-1", "A", "B", 10, T0), make_event("SM-2", "B", "C", 10, T0 + 1)])
    scan = detect_communities(store, window=WINDOW, min_size=2)
    assert scan.communities == [] or all(c.size >= 2 for c in scan.communities)


# --------------------------------------------------------------------- #
# centrality
# --------------------------------------------------------------------- #
def test_degree_metrics(store: GraphStore) -> None:
    ingest(
        store,
        [
            make_event("DG-1", "X", "Y", 100, T0),
            make_event("DG-2", "Z", "Y", 100, T0 + 1),
            make_event("DG-3", "Y", "W", 100, T0 + 2),
        ],
    )
    scan = compute_centrality(store, window=WINDOW)
    y = scan.for_account("Y")
    assert y["in_degree"] == 2
    assert y["out_degree"] == 1
    assert y["weighted_degree"] == 300
    assert "pagerank" in y
    assert "betweenness" in y


def test_bridge_node_identification(store: GraphStore) -> None:
    """An articulation point joining two clusters is reported as a bridge."""
    _two_community_store(store)
    scan = compute_centrality(store, window=WINDOW)
    # C1-A <-> C2-A is the only inter-cluster edge; one of them is a bridge
    assert "C1-A" in scan.bridge_nodes or "C2-A" in scan.bridge_nodes
    assert scan.top_pagerank and "account_id" in scan.top_pagerank[0]


def test_centrality_empty_graph(store: GraphStore) -> None:
    scan = compute_centrality(store, window=WINDOW)
    assert scan.metrics == {}
    assert scan.bridge_nodes == []
    payload = scan.to_dict()
    assert payload["accounts_measured"] == 0


def test_centrality_respects_window(store: GraphStore) -> None:
    ingest(store, [make_event("W-1", "A", "B", 10, T0), make_event("W-2", "C", "B", 10, T0 + 1)])
    empty = Window.between(T0 + 99_000, T0 + 100_000)
    scan = compute_centrality(store, window=empty)
    assert scan.metrics == {}


def test_centrality_deterministic(store: GraphStore) -> None:
    _two_community_store(store)
    a = compute_centrality(store, window=WINDOW)
    b = compute_centrality(store, window=WINDOW)
    assert a.for_account("C1-A") == b.for_account("C1-A")


@pytest.mark.parametrize("graph_empty", [True])
def test_betweenness_bounded_on_bigger_graph(graph_empty: bool) -> None:
    """Betweenness uses sampling on larger graphs (runtime stays bounded)."""
    g = nx.path_graph(50)
    # build a synthetic store from a path of 50 nodes
    from app.graph.graph_store import GraphStore
    from app.config import GraphConfig

    store = GraphStore(GraphConfig())
    for i in range(49):
        store.add_event(make_event(f"P-{i}", f"N{i}", f"N{i+1}", 10, T0 + i))
    scan = compute_centrality(store, window=WINDOW, max_nodes=5000, betweenness_sample=16)
    assert len(scan.metrics) == 50
    middle = scan.for_account("N25")
    assert middle["betweenness"] > 0
