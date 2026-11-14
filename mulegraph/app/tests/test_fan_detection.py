"""Fan-in / fan-out detection tests (positive and negative)."""

from __future__ import annotations

from app.algorithms.fan_detection import detect_fan_in, detect_fan_out, fan_result_to_pattern
from app.graph.adjacency_index import Window
from app.graph.graph_store import GraphStore

from .conftest import T0, ingest, make_event

WINDOW = Window.between(T0 - 60, T0 + 300)


# --------------------------------------------------------------------- #
# fan-in
# --------------------------------------------------------------------- #
def test_fan_in_detected(fan_in_store: GraphStore) -> None:
    result = detect_fan_in(fan_in_store, "ACC-TARGET", window=WINDOW)
    assert result.detected is True
    assert result.unique_accounts == 10
    assert result.transaction_count == 10
    assert result.total_amount == sum(5000 + i * 100 for i in range(10))
    assert result.amount_stats["min"] == 5000
    assert result.amount_stats["max"] == 5900
    assert len(result.transaction_ids) == 10
    assert result.concentration["peak_bucket_count"] >= 1


def test_fan_in_pattern_has_evidence(fan_in_store: GraphStore) -> None:
    result = detect_fan_in(fan_in_store, "ACC-TARGET", window=WINDOW)
    pattern = fan_result_to_pattern(result)
    assert pattern is not None
    assert pattern.pattern_type == "FAN_IN"
    assert "ACC-TARGET" in pattern.accounts_involved
    assert len(pattern.transaction_ids) == 10
    assert pattern.severity in ("HIGH", "CRITICAL", "MEDIUM")
    payload = pattern.to_dict()
    assert payload["algorithm"].startswith("fan_detection")
    assert payload["detection_parameters"]["min_unique_accounts"] >= 1


def test_fan_in_negative_single_source(store: GraphStore) -> None:
    """One source paying repeatedly must NOT trigger fan-in."""
    events = [make_event(f"NS-{i}", "ONLY-SRC", "ACC-X", 500, T0 + i) for i in range(10)]
    ingest(store, events)
    result = detect_fan_in(store, "ACC-X", window=WINDOW)
    assert result.detected is False
    assert result.unique_accounts == 1
    assert fan_result_to_pattern(result) is None


def test_fan_in_negative_fewer_than_threshold(store: GraphStore) -> None:
    """3 unique sources is below the default threshold of 5."""
    events = [make_event(f"TS-{i}", f"SRC-{i}", "ACC-Y", 500, T0 + i) for i in range(3)]
    ingest(store, events)
    result = detect_fan_in(store, "ACC-Y", window=WINDOW)
    assert result.detected is False
    assert result.unique_accounts == 3


def test_fan_in_ignores_non_settled(store: GraphStore) -> None:
    """Held/rejected/reversed/pending never count as incoming money."""
    from app.graph.models import TransactionStatus

    statuses = [
        TransactionStatus.HELD_FOR_VERIFICATION,
        TransactionStatus.REJECTED,
        TransactionStatus.REVERSED,
        TransactionStatus.PENDING,
    ]
    events = [
        make_event(f"NS-{i}", f"SRC-{i}", "ACC-Z", 500, T0 + i, status=s)
        for i, s in enumerate(statuses * 2)
    ]
    ingest(store, events)
    result = detect_fan_in(store, "ACC-Z", window=WINDOW)
    assert result.transaction_count == 0
    assert result.detected is False


def test_fan_in_window_filtering(fan_in_store: GraphStore) -> None:
    """A window covering none of the transactions finds nothing."""
    empty = Window.between(T0 + 10_000, T0 + 20_000)
    result = detect_fan_in(fan_in_store, "ACC-TARGET", window=empty)
    assert result.detected is False
    assert result.transaction_count == 0


# --------------------------------------------------------------------- #
# fan-out
# --------------------------------------------------------------------- #
def test_fan_out_detected(fan_out_store: GraphStore) -> None:
    result = detect_fan_out(fan_out_store, "ACC-SOURCE", window=WINDOW)
    assert result.detected is True
    assert result.unique_accounts == 10
    assert result.transaction_count == 10
    pattern = fan_result_to_pattern(result)
    assert pattern is not None and pattern.pattern_type == "FAN_OUT"


def test_fan_out_negative_one_destination(store: GraphStore) -> None:
    events = [make_event(f"OD-{i}", "ACC-D", "ONE-DST", 900, T0 + i) for i in range(12)]
    ingest(store, events)
    result = detect_fan_out(store, "ACC-D", window=WINDOW)
    assert result.detected is False
    assert result.unique_accounts == 1


def test_fan_metrics_include_concentration_and_distribution(fan_in_store: GraphStore) -> None:
    result = detect_fan_in(fan_in_store, "ACC-TARGET", window=WINDOW)
    assert "peak_share" in result.concentration
    assert "coefficient_of_variation" in result.amount_stats
    assert result.severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
