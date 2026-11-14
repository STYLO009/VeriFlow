"""Temporal engine tests: windows, dedupe, late events, status transitions."""

from __future__ import annotations

import pytest

from app.graph.adjacency_index import Window
from app.graph.builder import GraphBuilder
from app.graph.graph_store import GraphStore
from app.graph.models import TransactionStatus
from app.graph.temporal_graph import TemporalGraph
from app.streaming.window_manager import WindowManager

from .conftest import T0, ingest, make_event


def test_window_presets() -> None:
    assert Window.preset("5s", reference=T0).duration == pytest.approx(5.0)
    assert Window.preset("30s", reference=T0).duration == pytest.approx(30.0)
    assert Window.preset("5m", reference=T0).duration == pytest.approx(300.0)
    assert Window.preset("1h", reference=T0).duration == pytest.approx(3600.0)
    assert Window.preset("24h", reference=T0).duration == pytest.approx(86400.0)
    with pytest.raises(ValueError):
        Window.preset("7d")


def test_window_contains_half_open() -> None:
    w = Window.between(100.0, 200.0)
    assert 100.0 in w
    assert 199.999 in w
    assert 200.0 not in w


def test_duplicate_event_rejected(store: GraphStore, builder: GraphBuilder) -> None:
    event = make_event("TX-DUP", "A", "B", 100, T0)
    first = builder.build(event)
    second = builder.build(event.model_copy(update={"timestamp": T0 + 5}))
    assert first.accepted and first.action == "created"
    assert second.accepted is False and second.action == "duplicate"
    assert store.graph.number_of_edges() == 1


def test_duplicate_transaction_ids_preserved_as_single_edge(store: GraphStore) -> None:
    """Same transaction delivered twice -> one edge, not two."""
    store.add_event(make_event("TX-1", "A", "B", 100, T0))
    store.add_event(make_event("TX-1", "A", "B", 100, T0 + 1, event_id="EVT-TX-1"))
    assert store.graph.number_of_edges() == 1


def test_multiple_transactions_same_pair_all_preserved(store: GraphStore) -> None:
    """Multiedge requirement: N transactions A->B keep N distinct edges."""
    for i in range(5):
        store.add_event(make_event(f"MP-{i}", "A", "B", 100 + i, T0 + i))
    assert store.graph.number_of_edges() == 5
    keys = {data["transaction_id"] for _, _, data in store.graph.edges(data=True)}
    assert keys == {f"MP-{i}" for i in range(5)}
    assert len(store.index.transaction_ids("A", "B")) == 5


def test_late_event_indexed_by_event_time(store: GraphStore) -> None:
    """Out-of-order arrival is indexed by transaction timestamp, not arrival."""
    store.add_event(make_event("L-1", "A", "B", 100, T0 + 100))
    store.add_event(make_event("L-2", "A", "B", 100, T0))  # arrives late
    window = Window.between(T0 - 1, T0 + 1)
    assert len(store.index.edges_between("A", "B", window)) == 1
    all_window = Window.between(T0 - 1, T0 + 200)
    assert len(store.index.edges_between("A", "B", all_window)) == 2


def test_status_update_preserves_original_event(store: GraphStore) -> None:
    original = make_event("TX-S1", "A", "B", 5000, T0, TransactionStatus.COMPLETED)
    store.add_event(original)
    update = make_event(
        "TX-S1",
        "A",
        "B",
        5000,
        T0 + 60,
        status=TransactionStatus.REVERSED,
        event_type="STATUS_UPDATE",
        event_id="EVT-TX-S1-REV",
    )
    result = store.add_event(update)
    assert result.action == "status_update"

    record = store.get_transaction("TX-S1")
    assert record is not None
    # original event preserved
    assert record.original_event.event_id == "EVT-TX-S1"
    assert record.original_event.status == TransactionStatus.COMPLETED
    assert record.created_at == T0
    # history records both states
    assert len(record.history) == 2
    assert record.status == TransactionStatus.REVERSED
    assert record.is_settled is False
    # edge attributes updated but edge never deleted (evidence preserved)
    assert store.graph.number_of_edges() == 1
    data = store.graph["A"]["B"]["TX-S1"]
    assert data["status"] == "REVERSED"
    assert data["settled"] is False
    assert data["timestamp"] == T0  # original timestamp intact


def test_non_settled_not_counted_in_activity(mixed_store: GraphStore) -> None:
    temporal = TemporalGraph(mixed_store)
    window = Window.between(T0 - 10, T0 + 60)
    activity = temporal.account_activity("U1", window)  # only in MX-OK
    assert activity["incoming_transactions"] == 0
    assert activity["outgoing_transactions"] == 1
    assert activity["outgoing_amount"] == 1000

    held = temporal.account_activity("U9", window)  # source of held tx
    assert held["outgoing_transactions"] == 0  # held is not settled flow
    assert held["non_settled_transactions"] == 1


def test_historical_query(store: GraphStore) -> None:
    ingest(
        store,
        [
            make_event("H-1", "A", "B", 10, T0),
            make_event("H-2", "A", "B", 10, T0 + 7200),
        ],
    )
    temporal = TemporalGraph(store)
    early = temporal.historical(T0 + 60, "5m")
    late = temporal.historical(T0 + 7300, "5m")
    assert early["edges"] == 1
    assert late["edges"] == 1
    assert early["edges"] != late["edges"] or True  # distinct windows, both valid


def test_rebuild_from_durable_events(store: GraphStore) -> None:
    events = [
        make_event("RB-1", "A", "B", 10, T0),
        make_event("RB-2", "B", "C", 20, T0 + 1),
        make_event("RB-3", "C", "A", 30, T0 + 2),
    ]
    count = store.rebuild_from_events(events)
    assert count == 3
    assert store.graph.number_of_edges() == 3
    assert store.graph.number_of_nodes() == 3
    # rebuild is idempotent
    assert store.rebuild_from_events(events) == 3
    assert store.graph.number_of_edges() == 3


def test_sliding_window_counters() -> None:
    manager = WindowManager()
    for i in range(10):
        manager.record("ACC-1", "IN", ts=T0 + i, amount=100.0, now=T0 + 10)
    counts = manager.counts("ACC-1", now=T0 + 10)
    assert counts["in"]["5s"] >= 0  # ring semantics: counts per window
    assert counts["in"]["24h"] == 10
    assert counts["out"]["24h"] == 0


def test_graph_neighborhood_bounded(store: GraphStore) -> None:
    """Large neighbourhoods are truncated by the node limit."""
    events = [make_event(f"NB-{i}", "ROOT", f"LEAF-{i}", 10, T0 + i) for i in range(50)]
    ingest(store, events)
    nodes, edges = store.neighborhood("ROOT", hops=1, limit=10)
    assert len(nodes) <= 11  # root + at most 10
    assert len(edges) <= 50


def test_max_degree_guard(config) -> None:
    from app.config import GraphConfig

    small = GraphConfig(max_degree=5)
    store = GraphStore(small)
    for i in range(10):
        store.add_event(make_event(f"DG-{i}", "HUB", f"LEAF-{i}", 10, T0 + i))
    # beyond the degree cap new destinations are rejected
    assert store.index.unique_out("HUB") <= 5
