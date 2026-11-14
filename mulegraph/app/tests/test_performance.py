"""Performance tests under streaming load.

These are *measured* tests, not fabricated benchmarks: they ingest real events,
record latencies with ``time.perf_counter`` and assert generous upper bounds so
they fail loudly on a pathological regression while staying stable on slow CI
machines. Exact numbers are produced by ``scripts/benchmark.py``.
"""

from __future__ import annotations

import statistics
import time

import pytest

from app.algorithms.fan_detection import detect_fan_in
from app.algorithms.multi_hop import trace_money_flow
from app.config import GraphConfig
from app.graph.adjacency_index import Window
from app.graph.builder import GraphBuilder
from app.graph.graph_store import GraphStore
from app.intelligence.graph_analyzer import GraphAnalyzer
from app.simulator.synthetic import SyntheticTransactionGenerator
from app.streaming.event_processor import GraphEventProcessor

from .conftest import T0


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * (p / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


@pytest.mark.performance
def test_ingest_50_tps_for_5_seconds() -> None:
    """250 events at 50 TPS: p95 ingest latency must stay bounded."""
    store = GraphStore(GraphConfig())
    processor = GraphEventProcessor(GraphBuilder(store), store)
    gen = SyntheticTransactionGenerator(seed=1, events_per_second=50.0, start_ts=time.time() - 300)

    latencies: list[float] = []
    for _ in range(250):
        event = gen.next_event()
        started = time.perf_counter()
        processor.process(event)
        latencies.append((time.perf_counter() - started) * 1000.0)

    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)
    print(f"\n[50 TPS] ingest p50={p50:.3f}ms p95={p95:.3f}ms max={max(latencies):.3f}ms")
    assert store.graph.number_of_edges() >= 200  # duplicates excluded
    assert p95 < 25.0, f"p95 ingest latency {p95:.2f}ms exceeds 25ms budget"


@pytest.mark.performance
def test_ingest_100_tps_burst() -> None:
    """500 events ingested as fast as possible (100 TPS equivalent burst)."""
    store = GraphStore(GraphConfig())
    processor = GraphEventProcessor(GraphBuilder(store), store)
    gen = SyntheticTransactionGenerator(seed=2, events_per_second=100.0, start_ts=time.time() - 300)

    latencies: list[float] = []
    started_all = time.perf_counter()
    for _ in range(500):
        event = gen.next_event()
        started = time.perf_counter()
        processor.process(event)
        latencies.append((time.perf_counter() - started) * 1000.0)
    elapsed = time.perf_counter() - started_all
    throughput = 500 / elapsed

    print(
        f"\n[100 TPS burst] throughput={throughput:.0f} eps "
        f"p50={_percentile(latencies, 50):.3f}ms p95={_percentile(latencies, 95):.3f}ms "
        f"p99={_percentile(latencies, 99):.3f}ms"
    )
    assert throughput > 100, f"only {throughput:.0f} events/s ingested"
    assert _percentile(latencies, 95) < 30.0


@pytest.mark.performance
def test_analysis_latency_on_large_neighbourhood() -> None:
    """FAST analysis of a hub with 2000 counterparties stays interactive."""
    store = GraphStore(GraphConfig(max_degree=10_000))
    gen = SyntheticTransactionGenerator(seed=3, start_ts=T0)
    now = time.time()
    for i in range(3000):
        event = gen.next_event()
        # force timestamps near now so preset windows include them
        store.add_event(event.model_copy(update={"timestamp": now - 300 + i * 0.1}))

    analyzer = GraphAnalyzer(store)
    try:
        latencies: list[float] = []
        for _ in range(20):
            started = time.perf_counter()
            analyzer.analyze_account("ACC-0901", window="5m", profile="FAST", reference=now)
            latencies.append((time.perf_counter() - started) * 1000.0)
        p50 = statistics.median(latencies)
        p95 = _percentile(latencies, 95)
        print(f"\n[analysis FAST] p50={p50:.2f}ms p95={p95:.2f}ms nodes={store.graph.number_of_nodes()}")
        assert p95 < 500.0, f"FAST analysis p95 {p95:.1f}ms too slow"
    finally:
        analyzer.close()


@pytest.mark.performance
def test_windowed_queries_are_indexed() -> None:
    """Window queries use bisect (not full scans) - must stay fast."""
    store = GraphStore(GraphConfig(max_degree=20_000))
    for i in range(20_000):
        store.add_event(
            __import__("app.graph.models", fromlist=["TransactionEvent"]).TransactionEvent(
                event_id=f"EVT-PQ-{i}",
                transaction_id=f"PQ-{i}",
                source_account=f"A{i % 500}",
                destination_account="HUB",
                amount=10.0,
                timestamp=T0 + i * 0.01,
            )
        )
    window = Window.between(T0 + 100, T0 + 200)
    started = time.perf_counter()
    rows = store.index.in_neighbors("HUB", window)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    print(f"\n[window query] {len(rows)} rows in {elapsed_ms:.3f}ms over 20k edges")
    assert elapsed_ms < 5.0
    assert len(rows) > 0


@pytest.mark.performance
def test_trace_bounded_on_dense_graph() -> None:
    """Multi-hop tracing on a dense cluster terminates within budget."""
    from app.graph.models import TransactionEvent

    store = GraphStore(GraphConfig())
    gen = SyntheticTransactionGenerator(seed=4, start_ts=T0)
    for _ in range(2000):
        store.add_event(gen.next_event())
    window = Window.between(T0 - 60, T0 + 600)
    started = time.perf_counter()
    result = trace_money_flow(store, "ACC-0901", "ACC-0902", max_hops=4, window=window)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    print(f"\n[trace dense] paths={result.path_count} in {elapsed_ms:.2f}ms")
    assert elapsed_ms < 1000.0


@pytest.mark.performance
def test_fan_detection_latency() -> None:
    from app.graph.models import TransactionEvent

    store = GraphStore(GraphConfig())
    gen = SyntheticTransactionGenerator(seed=5, start_ts=time.time() - 300)
    for _ in range(2000):
        store.add_event(gen.next_event())
    window = Window.preset("24h")
    started = time.perf_counter()
    for i in range(50):
        detect_fan_in(store, f"ACC-{i:04d}", window=window)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    print(f"\n[fan scan] 50 accounts in {elapsed_ms:.2f}ms")
    assert elapsed_ms < 2000.0
