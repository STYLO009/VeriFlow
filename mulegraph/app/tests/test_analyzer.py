"""Unified analyzer + AI-ready output tests."""

from __future__ import annotations

from app.intelligence.graph_analyzer import AnalysisProfile, GraphAnalyzer
from app.graph.graph_store import GraphStore
from app.intelligence.subgraph_extractor import extract_subgraph

from .conftest import T0, ingest, make_event
from app.graph.adjacency_index import Window

WINDOW = Window.between(T0 - 60, T0 + 900)


def test_analyzer_standard_profile(fan_in_store: GraphStore) -> None:
    analyzer = GraphAnalyzer(fan_in_store)
    try:
        result = analyzer.analyze_account("ACC-TARGET", window="5m", profile="STANDARD", reference=T0 + 60)
        payload = result.to_dict()

        assert payload["analysis_status"] in ("completed", "completed_partial")
        assert payload["target_account"] == "ACC-TARGET"
        assert payload["time_window"] == "5m"
        assert payload["profile"] == "STANDARD"
        assert payload["graph_summary"]["incoming_transactions"] == 10
        assert any(p["pattern_type"] == "FAN_IN" for p in payload["detected_patterns"])
        assert payload["graph_evidence"]
        kinds = {e["kind"] for e in payload["graph_evidence"]}
        assert kinds == {"GRAPH_FACT", "DETECTED_PATTERN", "RISK_INTERPRETATION"}
        assert payload["analysis_metadata"]["graph_version"] == fan_in_store.version
        assert payload["analysis_metadata"]["execution_time_ms"] >= 0
        assert "fan_detection.detect_fan_in" in payload["analysis_metadata"]["algorithms_executed"]
        # fan-in of 10 sources should escalate severity
        assert payload["risk_assessment"]["severity"] in ("HIGH", "CRITICAL", "MEDIUM")
        assert payload["risk_assessment"]["signals"]
        for signal in payload["risk_assessment"]["signals"]:
            assert "weight" in signal and "contribution" in signal
    finally:
        analyzer.close()


def test_analyzer_fast_profile_runs_fewer_algorithms(fan_in_store: GraphStore) -> None:
    analyzer = GraphAnalyzer(fan_in_store)
    try:
        fast = analyzer.analyze_account("ACC-TARGET", window="5m", profile="FAST", reference=T0 + 60)
        standard = analyzer.analyze_account("ACC-TARGET", window="5m", profile="STANDARD", reference=T0 + 60)
        assert len(fast.analysis_metadata["algorithms_executed"]) < len(
            standard.analysis_metadata["algorithms_executed"]
        )
        assert "cycle_detection.find_cycles" not in fast.analysis_metadata["algorithms_executed"]
        assert "cycle_detection.find_cycles" in standard.analysis_metadata["algorithms_executed"]
    finally:
        analyzer.close()


def test_analyzer_deep_profile(cycle_store: GraphStore) -> None:
    analyzer = GraphAnalyzer(cycle_store)
    try:
        result = analyzer.analyze_account(
            "ACC-A", window="5m", profile="DEEP", reference=T0 + 60, include_subgraph=True
        )
        payload = result.to_dict()
        assert payload["profile"] == "DEEP"
        assert "community_detection.detect_communities" in payload["analysis_metadata"]["algorithms_executed"]
        assert "centrality.compute_centrality" in payload["analysis_metadata"]["algorithms_executed"]
        assert "multi_hop.trace_money_flow" in payload["analysis_metadata"]["algorithms_executed"]
        assert payload["subgraph"] is not None
        assert payload["subgraph"]["root"] == "ACC-A"
        assert any(p["pattern_type"] == "CIRCULAR_TRANSACTION" for p in payload["detected_patterns"])
    finally:
        analyzer.close()


def test_analyzer_unknown_account(store: GraphStore) -> None:
    analyzer = GraphAnalyzer(store)
    try:
        result = analyzer.analyze_account("GHOST")
        assert result.status == "account_not_found"
        assert result.to_dict()["graph_summary"]["nodes"] == 0
    finally:
        analyzer.close()


def test_analyzer_transaction_analysis(cycle_store: GraphStore) -> None:
    analyzer = GraphAnalyzer(cycle_store)
    try:
        result = analyzer.analyze_transaction("CY-2", profile="STANDARD")
        assert result is not None
        payload = result.to_dict()
        assert payload["target_transaction"] == "CY-2"
        assert payload["target_account"] == "ACC-C"
        assert payload["graph_summary"]["related_transaction"]["transaction_id"] == "CY-2"
        assert analyzer.analyze_transaction("NO-SUCH-TX") is None
    finally:
        analyzer.close()


def test_evidence_references_real_transactions(fan_in_store: GraphStore) -> None:
    """No fabricated evidence: every referenced tx id exists in the store."""
    analyzer = GraphAnalyzer(fan_in_store)
    try:
        result = analyzer.analyze_account("ACC-TARGET", window="5m", profile="STANDARD", reference=T0 + 60)
        payload = result.to_dict()
        referenced: set[str] = set()
        for pattern in payload["detected_patterns"]:
            referenced.update(pattern["transaction_ids"])
        for evidence in payload["graph_evidence"]:
            referenced.update(evidence.get("transaction_ids", []))
        assert referenced
        for tx_id in referenced:
            assert fan_in_store.get_transaction(tx_id) is not None, f"fabricated tx {tx_id}"
    finally:
        analyzer.close()


def test_subgraph_extraction(fan_in_store: GraphStore) -> None:
    view = extract_subgraph(fan_in_store, "ACC-TARGET", hops=1, window=WINDOW)
    payload = view.to_dict()
    assert payload["node_count"] == 11
    assert payload["edge_count"] == 10
    target = next(n for n in payload["nodes"] if n["is_target"])
    assert target["account_id"] == "ACC-TARGET"
    for edge in payload["edges"]:
        assert edge["transaction_id"].startswith("FI-")
        assert edge["settled"] is True


def test_analyzer_deterministic_for_same_input(cycle_store: GraphStore) -> None:
    analyzer = GraphAnalyzer(cycle_store)
    try:
        a = analyzer.analyze_account("ACC-A", window="5m", profile="STANDARD", reference=T0 + 60)
        b = analyzer.analyze_account("ACC-A", window="5m", profile="STANDARD", reference=T0 + 60)
        assert a.graph_summary == b.graph_summary
        pa = [p["pattern_id"] for p in a.detected_patterns]
        pb = [p["pattern_id"] for p in b.detected_patterns]
        assert pa == pb  # stable pattern ids across runs
    finally:
        analyzer.close()


def test_profile_enum_values() -> None:
    assert AnalysisProfile.FAST.value == "FAST"
    assert AnalysisProfile.STANDARD.value == "STANDARD"
    assert AnalysisProfile.DEEP.value == "DEEP"
