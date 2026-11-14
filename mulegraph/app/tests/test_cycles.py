"""Circular transaction detection tests."""

from __future__ import annotations

from app.algorithms.cycle_detection import canonical_cycle, cycles_to_patterns, find_cycles
from app.graph.adjacency_index import Window
from app.graph.graph_store import GraphStore

from .conftest import T0, ingest, make_event

WINDOW = Window.between(T0 - 60, T0 + 600)


def test_simple_cycle_detected(cycle_store: GraphStore) -> None:
    scan = find_cycles(cycle_store, window=WINDOW, min_length=3, max_length=3)
    assert scan.count == 1
    cycle = scan.cycles[0]
    assert canonical_cycle(cycle.accounts) == ("ACC-A", "ACC-B", "ACC-C")
    assert len(cycle.transaction_ids) == 3
    assert set(cycle.transaction_ids) == {"CY-1", "CY-2", "CY-3"}
    assert cycle.length == 3
    assert cycle.total_amount == 30_000
    assert len(cycle.timestamps) == 3
    assert len(cycle.amounts) == 3


def test_cycle_pattern_evidence(cycle_store: GraphStore) -> None:
    scan = find_cycles(cycle_store, window=WINDOW)
    patterns = cycles_to_patterns(scan)
    assert patterns, "expected at least one pattern"
    circular = [p for p in patterns if p.pattern_type == "CIRCULAR_TRANSACTION"]
    assert circular
    payload = circular[0].to_dict()
    assert "ACC-A" in payload["accounts_involved"]
    assert payload["supporting_metrics"]["cycle_length"] == 3
    assert payload["explanation"].startswith("Funds moved in a closed loop")


def test_four_node_cycle(store: GraphStore) -> None:
    events = [
        make_event("C4-1", "P", "Q", 100, T0),
        make_event("C4-2", "Q", "R", 100, T0 + 1),
        make_event("C4-3", "R", "S", 100, T0 + 2),
        make_event("C4-4", "S", "P", 100, T0 + 3),
    ]
    ingest(store, events)
    scan = find_cycles(store, window=WINDOW, min_length=3, max_length=4)
    assert scan.count == 1
    assert scan.cycles[0].length == 4


def test_no_cycle_in_linear_flow(chain_store: GraphStore) -> None:
    scan = find_cycles(chain_store, window=WINDOW)
    assert scan.count == 0
    assert cycles_to_patterns(scan) == []


def test_negative_single_edge(store: GraphStore) -> None:
    ingest(store, [make_event("SE-1", "X", "Y", 10, T0)])
    assert find_cycles(store, window=WINDOW).count == 0


def test_cycle_length_bounds(store: GraphStore) -> None:
    """A 4-node cycle must not be reported when max_length is 3."""
    events = [
        make_event("B-1", "A1", "B1", 10, T0),
        make_event("B-2", "B1", "C1", 10, T0 + 1),
        make_event("B-3", "C1", "D1", 10, T0 + 2),
        make_event("B-4", "D1", "A1", 10, T0 + 3),
    ]
    ingest(store, events)
    assert find_cycles(store, window=WINDOW, min_length=3, max_length=3).count == 0
    assert find_cycles(store, window=WINDOW, min_length=4, max_length=4).count == 1


def test_no_duplicates_from_multiple_starts(store: GraphStore) -> None:
    """The same loop must be reported exactly once regardless of start node."""
    events = [
        make_event("D-1", "Z1", "Z2", 10, T0),
        make_event("D-2", "Z2", "Z3", 10, T0 + 1),
        make_event("D-3", "Z3", "Z1", 10, T0 + 2),
    ]
    ingest(store, events)
    scan = find_cycles(store, window=WINDOW, min_length=3, max_length=5)
    assert scan.count == 1


def test_repeated_circular_activity(store: GraphStore) -> None:
    """Two executions of the same loop inside one window."""
    events = []
    for rep in range(2):
        base = T0 + rep * 60
        events += [
            make_event(f"R{rep}-1", "K1", "K2", 500, base),
            make_event(f"R{rep}-2", "K2", "K3", 500, base + 2),
            make_event(f"R{rep}-3", "K3", "K1", 500, base + 4),
        ]
    ingest(store, events)
    scan = find_cycles(store, window=WINDOW)
    assert scan.repeat_groups, "expected repeated activity group"
    assert scan.repeat_groups[0]["occurrences"] == 2
    patterns = cycles_to_patterns(scan)
    assert any(p.pattern_type == "REPEATED_CIRCULAR_ACTIVITY" for p in patterns)


def test_cycle_respects_window(cycle_store: GraphStore) -> None:
    empty = Window.between(T0 + 100_000, T0 + 200_000)
    assert find_cycles(cycle_store, window=empty).count == 0


def test_cycle_ignores_non_settled(store: GraphStore) -> None:
    """A loop made of reversed transactions must not be reported."""
    from app.graph.models import TransactionStatus

    events = [
        make_event("NR-1", "N1", "N2", 10, T0, TransactionStatus.REVERSED),
        make_event("NR-2", "N2", "N3", 10, T0 + 1, TransactionStatus.REVERSED),
        make_event("NR-3", "N3", "N1", 10, T0 + 2, TransactionStatus.REVERSED),
    ]
    ingest(store, events)
    assert find_cycles(store, window=WINDOW).count == 0


def test_max_cycles_limit(cycle_store: GraphStore) -> None:
    scan = find_cycles(cycle_store, window=WINDOW, max_cycles=1)
    assert scan.count <= 1
