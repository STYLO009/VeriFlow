"""Streaming event processor tests: dedupe, windows, evidence publishing."""

from __future__ import annotations

from app.graph.builder import GraphBuilder
from app.graph.graph_store import GraphStore
from app.graph.models import TransactionStatus
from app.streaming.event_processor import CollectingSink, GraphEventProcessor
from app.streaming.window_manager import WindowManager
from app.streaming.consumer import ListEventSource, run_stream

from .conftest import T0, make_event


def make_processor(store: GraphStore, sink=None) -> GraphEventProcessor:
    return GraphEventProcessor(
        GraphBuilder(store), store, window_manager=WindowManager(), sink=sink
    )


def test_process_creates_and_publishes(store: GraphStore) -> None:
    sink = CollectingSink()
    processor = make_processor(store, sink)
    result = processor.process(make_event("SP-1", "A", "B", 100, T0))
    assert result.accepted is True
    assert result.published is True
    assert result.analysis["profile"] == "FAST"
    assert len(sink.items) == 1
    payload = sink.items[0]
    assert payload["transaction_id"] == "SP-1"
    assert payload["analysis"]["target_account"] == "B"
    assert payload["analysis"]["graph_evidence"]
    assert payload["processing_latency_ms"] >= 0


def test_duplicate_event_not_processed_twice(store: GraphStore) -> None:
    sink = CollectingSink()
    processor = make_processor(store, sink)
    event = make_event("SP-2", "A", "B", 100, T0)
    first = processor.process(event)
    second = processor.process(event)
    assert first.accepted is True
    assert second.accepted is False
    assert second.action == "duplicate"
    assert len(sink.items) == 1
    assert processor.stats()["windows"]["duplicate_events"] == 1


def test_late_event_accepted_with_original_timestamp(store: GraphStore) -> None:
    processor = make_processor(store)
    late = make_event("SP-3", "A", "B", 100, T0 - 3600)
    result = processor.process(late)
    assert result.accepted is True
    record = store.get_transaction("SP-3")
    assert record is not None and record.created_at == T0 - 3600


def test_status_update_flow(store: GraphStore) -> None:
    sink = CollectingSink()
    processor = make_processor(store, sink)
    processor.process(make_event("SP-4", "A", "B", 100, T0))
    update = make_event(
        "SP-4",
        "A",
        "B",
        100,
        T0 + 30,
        status=TransactionStatus.REVERSED,
        event_type="STATUS_UPDATE",
        event_id="EVT-SP-4-REV",
    )
    result = processor.process(update)
    assert result.accepted is True
    assert result.action == "status_update"
    record = store.get_transaction("SP-4")
    assert record is not None and record.is_settled is False
    # both events remain observable
    assert store.graph.number_of_edges() == 1


def test_invalid_event_raises(store: GraphStore) -> None:
    import pytest
    from pydantic import ValidationError

    processor = make_processor(store)
    with pytest.raises(ValidationError):
        processor.process({"event_id": "", "transaction_id": "X"})  # type: ignore[arg-type]


def test_sink_failure_does_not_break_ingestion(store: GraphStore) -> None:
    def bad_sink(payload: dict) -> None:
        raise RuntimeError("broker down")

    processor = make_processor(store, sink=bad_sink)
    result = processor.process(make_event("SP-5", "A", "B", 100, T0))
    assert result.accepted is True
    assert result.published is False
    assert store.graph.number_of_edges() == 1


def test_run_stream_processes_events(store: GraphStore) -> None:
    events = [make_event(f"RS-{i}", "A", f"B-{i}", 10, T0 + i) for i in range(25)]
    processor = make_processor(store, CollectingSink())
    stats = run_stream(ListEventSource(events), processor, max_events=25, batch_size=10)
    assert stats["events"] == 25
    assert stats["published"] == 25
    assert store.graph.number_of_edges() == 25


def test_window_manager_tracks_counts(store: GraphStore) -> None:
    processor = make_processor(store)
    for i in range(8):
        processor.process(make_event(f"WM-{i}", f"S-{i}", "HUB", 500, T0 + i))
    counts = processor.windows.counts("HUB", now=T0 + 10)
    assert counts["in"]["24h"] == 8
    assert counts["in"]["5m"] == 8
    assert counts["out"]["24h"] == 0
    stats = processor.stats()
    assert stats["processed"] == 8
