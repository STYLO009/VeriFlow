"""Risk propagation tests (bounded, decaying, explainable)."""

from __future__ import annotations

from app.algorithms.risk_propagation import propagate_risk, seeds_from_patterns
from app.graph.adjacency_index import Window
from app.graph.graph_store import GraphStore

from .conftest import T0, ingest, make_event

WINDOW = Window.between(T0 - 60, T0 + 900)


def _line_store(store: GraphStore) -> GraphStore:
    """A -> B -> C -> D -> E linear chain of settled transactions."""
    events = [
        make_event(f"RP-{i}", f"N{i}", f"N{i + 1}", 1000, T0 + i) for i in range(1, 5)
    ]
    return ingest(store, events)


def test_propagation_decays_with_distance(store: GraphStore) -> None:
    _line_store(store)
    result = propagate_risk(store, {"N1": 1.0}, window=WINDOW, depth=3, decay=0.5)
    by_account = {n.account_id: n for n in result.nodes}
    assert "N2" in by_account
    assert "N3" in by_account
    assert "N4" in by_account
    assert "N5" not in by_account  # 4 hops > depth 3
    assert by_account["N2"].risk_score > by_account["N3"].risk_score
    assert by_account["N3"].risk_score > by_account["N4"].risk_score
    assert by_account["N2"].distance_hops == 1
    assert by_account["N4"].distance_hops == 3


def test_propagation_explains_paths(store: GraphStore) -> None:
    _line_store(store)
    result = propagate_risk(store, {"N1": 0.9}, window=WINDOW, depth=2)
    node = next(n for n in result.nodes if n.account_id == "N3")
    payload = node.to_dict()
    assert payload["seed_account"] == "N1"
    assert payload["distance_hops"] == 2
    assert len(payload["path"]) == 2
    assert payload["path"][0]["transaction_id"].startswith("RP-")
    assert "not proof" in payload["explanation"] or "not proof of wrongdoing" in payload["explanation"]
    assert payload["association_only"] is True


def test_propagation_depth_zero_stops(store: GraphStore) -> None:
    _line_store(store)
    result = propagate_risk(store, {"N1": 1.0}, window=WINDOW, depth=0)
    assert result.nodes == []


def test_propagation_no_unlimited_spread(store: GraphStore) -> None:
    """A star with 100 neighbours must not spread beyond the depth limit."""
    events = [make_event(f"ST-{i}", "CENTER", f"LEAF-{i}", 10, T0 + i) for i in range(100)]
    events += [make_event(f"ST2-{i}", f"LEAF-{i}", f"OUT-{i}", 10, T0 + 100 + i) for i in range(100)]
    ingest(store, events)
    result = propagate_risk(store, {"CENTER": 1.0}, window=WINDOW, depth=1)
    assert all(n.distance_hops <= 1 for n in result.nodes)
    assert len(result.nodes) <= 100


def test_propagation_requires_known_seed(store: GraphStore) -> None:
    _line_store(store)
    result = propagate_risk(store, {"GHOST": 1.0}, window=WINDOW, depth=2)
    assert result.nodes == []


def test_propagation_window_filtering(store: GraphStore) -> None:
    _line_store(store)
    empty = Window.between(T0 + 90_000, T0 + 100_000)
    result = propagate_risk(store, {"N1": 1.0}, window=empty, depth=3)
    assert result.nodes == []


def test_seed_extraction_only_high_severity() -> None:
    from app.algorithms.common import Pattern
    from app.graph.adjacency_index import Window

    high = Pattern(
        pattern_type="FAN_IN",
        pattern_id="X",
        accounts_involved=["BAD-1", "BAD-2"],
        transaction_ids=["T1"],
        amounts=[1],
        timestamps=[1],
        window=None,
        algorithm="test",
        severity="HIGH",
    )
    low = Pattern(
        pattern_type="FAN_IN",
        pattern_id="Y",
        accounts_involved=["OK-1"],
        transaction_ids=["T2"],
        amounts=[1],
        timestamps=[1],
        window=None,
        algorithm="test",
        severity="LOW",
    )
    seeds = seeds_from_patterns([high, low])
    assert "BAD-1" in seeds and "BAD-2" in seeds
    assert "OK-1" not in seeds


def test_seed_accounts_excluded_from_own_propagation(store: GraphStore) -> None:
    """Seeds appear as direct (distance 0) nodes with association_only False."""
    _line_store(store)
    result = propagate_risk(store, {"N1": 0.8}, window=WINDOW, depth=1)
    # seeds are not returned in `nodes` (only propagated accounts are)
    assert all(n.distance_hops >= 1 for n in result.nodes)
    assert result.seeds == {"N1": 0.8}
