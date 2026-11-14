"""Temporal motif detection tests."""

from __future__ import annotations

from app.algorithms.temporal_motifs import MotifParams, detect_temporal_motifs
from app.graph.adjacency_index import Window
from app.graph.graph_store import GraphStore

from .conftest import T0, ingest, make_event

WINDOW = Window.between(T0 - 60, T0 + 900)


def test_fan_in_then_fan_out_detected(store: GraphStore) -> None:
    events = []
    # 5 accounts pay HUB within 30s
    for i in range(5):
        events.append(make_event(f"MF-IN-{i}", f"S-{i}", "HUB", 10_000, T0 + i * 5))
    # HUB distributes to 5 destinations in the next 60s
    for i in range(5):
        events.append(make_event(f"MF-OUT-{i}", "HUB", f"D-{i}", 9_500, T0 + 40 + i * 5))
    ingest(store, events)

    scan = detect_temporal_motifs(store, window=WINDOW)
    types = {p.pattern_type for p in scan.patterns}
    assert "FAN_IN_THEN_FAN_OUT" in types
    motif = next(p for p in scan.patterns if p.pattern_type == "FAN_IN_THEN_FAN_OUT")
    assert "HUB" in motif.accounts_involved
    assert len(motif.transaction_ids) == 10
    assert motif.metrics["inbound_accounts"] == 5
    assert motif.metrics["outbound_accounts"] == 5


def test_fan_in_only_no_motif(store: GraphStore) -> None:
    """Fan-in without subsequent distribution must not trigger the motif."""
    events = [make_event(f"FI-{i}", f"S-{i}", "LONELY", 10_000, T0 + i * 5) for i in range(6)]
    ingest(store, events)
    scan = detect_temporal_motifs(store, window=WINDOW)
    assert "FAN_IN_THEN_FAN_OUT" not in {p.pattern_type for p in scan.patterns}


def test_rapid_distribution_detected(store: GraphStore) -> None:
    events = [
        make_event("RD-IN-1", "BIG-SENDER", "PASS", 100_000, T0),
        make_event("RD-IN-2", "BIG-SENDER-2", "PASS", 50_000, T0 + 5),
    ]
    for i in range(3):
        events.append(make_event(f"RD-OUT-{i}", "PASS", f"OUT-{i}", 45_000, T0 + 20 + i * 5))
    ingest(store, events)
    scan = detect_temporal_motifs(store, window=WINDOW)
    assert "RAPID_DISTRIBUTION" in {p.pattern_type for p in scan.patterns}


def test_sequential_chain_detected(store: GraphStore) -> None:
    events = [
        make_event("SC-1", "CH-1", "CH-2", 50_000, T0),
        make_event("SC-2", "CH-2", "CH-3", 50_000, T0 + 10),
        make_event("SC-3", "CH-3", "CH-4", 50_000, T0 + 20),
    ]
    ingest(store, events)
    scan = detect_temporal_motifs(
        store, window=WINDOW, params=MotifParams(chain_length=3, max_hop_gap_seconds=30)
    )
    chains = [p for p in scan.patterns if p.pattern_type == "SEQUENTIAL_CHAIN"]
    assert chains, "expected a sequential chain motif"
    assert chains[0].metrics["chain_length"] == 3


def test_slow_chain_not_detected(store: GraphStore) -> None:
    """Hops spaced hours apart are not a rapid sequential motif."""
    events = [
        make_event("SL-1", "SL-1", "SL-2", 50_000, T0),
        make_event("SL-2", "SL-2", "SL-3", 50_000, T0 + 3600),
        make_event("SL-3", "SL-3", "SL-4", 50_000, T0 + 7200),
    ]
    ingest(store, events)
    scan = detect_temporal_motifs(
        store, window=Window.between(T0 - 60, T0 + 10_000),
        params=MotifParams(chain_length=3, max_hop_gap_seconds=30),
    )
    assert "SEQUENTIAL_CHAIN" not in {p.pattern_type for p in scan.patterns}


def test_repeated_circular_motif(store: GraphStore) -> None:
    events = []
    for rep in range(2):
        base = T0 + rep * 30
        events += [
            make_event(f"RC{rep}-1", "Q1", "Q2", 1000, base),
            make_event(f"RC{rep}-2", "Q2", "Q3", 1000, base + 2),
            make_event(f"RC{rep}-3", "Q3", "Q1", 1000, base + 4),
        ]
    ingest(store, events)
    scan = detect_temporal_motifs(store, window=WINDOW)
    assert "REPEATED_CIRCULAR" in {p.pattern_type for p in scan.patterns}


def test_empty_graph_no_motifs(store: GraphStore) -> None:
    scan = detect_temporal_motifs(store, window=WINDOW)
    assert scan.patterns == []
    assert scan.to_dict()["motif_count"] == 0
