"""Multi-hop money-flow tracing tests."""

from __future__ import annotations

from app.algorithms.multi_hop import trace_money_flow
from app.graph.adjacency_index import Window
from app.graph.graph_store import GraphStore

from .conftest import T0, ingest, make_event

WINDOW = Window.between(T0 - 60, T0 + 600)


def test_four_hop_path_found(chain_store: GraphStore) -> None:
    result = trace_money_flow(chain_store, "S1", "DEST", max_hops=5, window=WINDOW)
    assert result.path_count >= 1
    path = result.paths[0]
    assert path.hop_count == 4
    assert path.accounts == ["S1", "S2", "S3", "S4", "DEST"]
    assert path.transaction_ids == ["MH-1", "MH-2", "MH-3", "MH-4"]
    assert path.total_amount == 9000 + 8500 + 8000 + 7500
    assert path.min_hop_amount == 7500
    assert path.chronological is True


def test_hop_limit_blocks_path(chain_store: GraphStore) -> None:
    result = trace_money_flow(chain_store, "S1", "DEST", max_hops=2, window=WINDOW)
    assert result.path_count == 0
    assert result.shortest_hops is None


def test_negative_no_path(store: GraphStore) -> None:
    ingest(store, [make_event("NP-1", "L1", "L2", 10, T0)])
    result = trace_money_flow(store, "L1", "ISOLATED", window=WINDOW)
    assert result.path_count == 0


def test_min_amount_filter(store: GraphStore) -> None:
    events = [
        make_event("MA-1", "A", "B", 100, T0),
        make_event("MA-2", "B", "C", 50_000, T0 + 1),
    ]
    ingest(store, events)
    loose = trace_money_flow(store, "A", "C", window=WINDOW, min_amount=10)
    strict = trace_money_flow(store, "A", "C", window=WINDOW, min_amount=1000)
    assert loose.path_count == 1
    assert strict.path_count == 0  # first hop is below the threshold


def test_shortest_only(chain_store: GraphStore) -> None:
    ingest(
        chain_store,
        [
            make_event("ALT-1", "S1", "ALT", 100, T0),
            make_event("ALT-2", "ALT", "DEST", 100, T0 + 1),
        ],
    )
    all_paths = trace_money_flow(chain_store, "S1", "DEST", max_hops=5, window=WINDOW)
    shortest = trace_money_flow(chain_store, "S1", "DEST", max_hops=5, window=WINDOW, shortest_only=True)
    assert all_paths.path_count >= 2  # 4-hop and 2-hop routes
    assert shortest.path_count == 1
    assert shortest.paths[0].hop_count == 2


def test_chronological_ordering(chain_store: GraphStore) -> None:
    result = trace_money_flow(chain_store, "S1", "DEST", max_hops=5, window=WINDOW)
    path = result.paths[0]
    stamps = [h.timestamp for h in path.hops]
    assert stamps == sorted(stamps)


def test_strict_chronological_rejects_backwards_time(store: GraphStore) -> None:
    """S -> D exists but its timestamp precedes the first hop."""
    events = [
        make_event("BT-1", "A", "B", 100, T0 + 10),
        make_event("BT-2", "B", "C", 100, T0),  # travels backwards in time
    ]
    ingest(store, events)
    loose = trace_money_flow(store, "A", "C", window=WINDOW, strict_chronological=False)
    strict = trace_money_flow(store, "A", "C", window=WINDOW, strict_chronological=True)
    assert loose.path_count == 1
    assert strict.path_count == 0


def test_non_settled_not_traced(mixed_store: GraphStore) -> None:
    """Only MX-OK (U1 -> U2) is settled; no path U1 -> U10 exists."""
    result = trace_money_flow(mixed_store, "U1", "U10", window=WINDOW)
    assert result.path_count == 0


def test_window_filtering(chain_store: GraphStore) -> None:
    empty = Window.between(T0 + 100_000, T0 + 200_000)
    assert trace_money_flow(chain_store, "S1", "DEST", window=empty).path_count == 0


def test_path_evidence_structure(chain_store: GraphStore) -> None:
    result = trace_money_flow(chain_store, "S1", "DEST", max_hops=5, window=WINDOW)
    payload = result.to_dict()
    hop = payload["paths"][0]["hops"][0]
    assert set(hop) >= {"position", "from_account", "to_account", "transaction_id", "timestamp", "amount", "status"}
    assert payload["detection_parameters"]["max_hops"] == 5
    assert payload["source"] == "S1"
    assert payload["destination"] == "DEST"
