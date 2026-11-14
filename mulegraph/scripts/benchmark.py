"""Performance benchmark for the MuleGraph graph engine.

Runs a real synthetic workload through the streaming pipeline and reports
*measured* numbers only:

* ingest throughput (transactions/second) and graph update latency
* analysis latency p50 / p95 / p99 (FAST profile)
* memory consumption (tracemalloc + process working set)

Usage (PowerShell):
    .\\.venv\\Scripts\\python.exe scripts\\benchmark.py --tps 50  --duration 10
    .\\.venv\\Scripts\\python.exe scripts\\benchmark.py --tps 100 --duration 10
    .\\.venv\\Scripts\\python.exe scripts\\benchmark.py --tps 500 --duration 10   # stress
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import tracemalloc
from pathlib import Path

# allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import GraphConfig  # noqa: E402
from app.graph.builder import GraphBuilder  # noqa: E402
from app.graph.graph_store import GraphStore  # noqa: E402
from app.intelligence.graph_analyzer import GraphAnalyzer  # noqa: E402
from app.simulator.synthetic import SyntheticTransactionGenerator  # noqa: E402
from app.streaming.event_processor import CollectingSink, GraphEventProcessor  # noqa: E402


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * (p / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def process_memory_mb() -> float | None:
    """Best-effort resident memory of this process (Windows friendly)."""
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetCurrentProcess()
        get_info = getattr(kernel32, "K32GetProcessMemoryInfo", None) or getattr(
            ctypes.windll.psapi, "GetProcessMemoryInfo", None
        )
        if get_info is None:
            return None
        get_info.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
            wintypes.DWORD,
        ]
        get_info.restype = wintypes.BOOL
        if get_info(handle, ctypes.byref(counters), counters.cb):
            return round(counters.WorkingSetSize / (1024 * 1024), 2)
    except Exception:
        pass
    return None


def run_benchmark(tps: int, duration: float, profile: str, analyze_every: int) -> dict:
    config = GraphConfig()
    store = GraphStore(config)
    sink = CollectingSink(limit=1000)
    processor = GraphEventProcessor(GraphBuilder(store), store, sink=sink)
    analyzer = GraphAnalyzer(store)
    generator = SyntheticTransactionGenerator(
        seed=1234, events_per_second=float(tps), start_ts=time.time() - 600
    )

    total_events = int(tps * duration)
    ingest_latencies: list[float] = []
    analysis_latencies: list[float] = []

    tracemalloc.start()
    started = time.perf_counter()
    deadline = started + duration

    try:
        for i in range(total_events):
            event = generator.next_event()

            t0 = time.perf_counter()
            processor.process(event)
            ingest_latencies.append((time.perf_counter() - t0) * 1000.0)

            if analyze_every and i % analyze_every == 0:
                t1 = time.perf_counter()
                analyzer.analyze_account(
                    event.destination_account, window="5m", profile=profile,
                    reference=event.timestamp,
                )
                analysis_latencies.append((time.perf_counter() - t1) * 1000.0)

            # pace to the requested TPS (best effort)
            expected = (i + 1) / tps
            elapsed = time.perf_counter() - started
            if expected > elapsed:
                time.sleep(expected - elapsed)
    finally:
        wall = time.perf_counter() - started
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        analyzer.close()

    graph_stats = store.stats()
    window_stats = processor.windows.stats()

    result = {
        "target_tps": tps,
        "duration_seconds": round(wall, 3),
        "events": total_events,
        "effective_throughput_tps": round(total_events / wall, 2),
        "graph": {
            "nodes": graph_stats["nodes"],
            "edges": graph_stats["edges"],
            "transactions": graph_stats["transactions"],
        },
        "ingest_latency_ms": {
            "p50": round(percentile(ingest_latencies, 50), 4),
            "p95": round(percentile(ingest_latencies, 95), 4),
            "p99": round(percentile(ingest_latencies, 99), 4),
            "mean": round(sum(ingest_latencies) / len(ingest_latencies), 4)
            if ingest_latencies
            else 0.0,
            "max": round(max(ingest_latencies), 4) if ingest_latencies else 0.0,
        },
        "analysis_latency_ms": {
            "samples": len(analysis_latencies),
            "p50": round(percentile(analysis_latencies, 50), 3),
            "p95": round(percentile(analysis_latencies, 95), 3),
            "p99": round(percentile(analysis_latencies, 99), 3),
        },
        "memory": {
            "tracemalloc_peak_mb": round(peak / (1024 * 1024), 2),
            "tracemalloc_current_mb": round(current / (1024 * 1024), 2),
            "process_working_set_mb": process_memory_mb(),
        },
        "window_counters": window_stats,
        "evidence_published": len(sink.items),
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="MuleGraph performance benchmark")
    parser.add_argument("--tps", type=int, default=50, help="target transactions per second")
    parser.add_argument("--duration", type=float, default=10.0, help="seconds to run")
    parser.add_argument("--profile", default="FAST", choices=["FAST", "STANDARD", "DEEP"])
    parser.add_argument(
        "--analyze-every", type=int, default=10,
        help="run one analysis every N events (0 disables analysis timing)",
    )
    parser.add_argument("--json", action="store_true", help="emit raw JSON only")
    args = parser.parse_args()

    result = run_benchmark(args.tps, args.duration, args.profile, args.analyze_every)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print()
    print("=" * 68)
    print(f" MuleGraph benchmark  |  target {args.tps} TPS  |  {args.duration}s")
    print("=" * 68)
    print(f" events processed          : {result['events']}")
    print(f" effective throughput      : {result['effective_throughput_tps']} tx/s")
    print(f" graph size                : {result['graph']['nodes']} nodes / {result['graph']['edges']} edges")
    print(f" ingest latency p50/p95/p99: {result['ingest_latency_ms']['p50']} / "
          f"{result['ingest_latency_ms']['p95']} / {result['ingest_latency_ms']['p99']} ms")
    print(f" analysis latency p50/p95  : {result['analysis_latency_ms']['p50']} / "
          f"{result['analysis_latency_ms']['p95']} ms "
          f"(n={result['analysis_latency_ms']['samples']}, profile={args.profile})")
    print(f" memory (tracemalloc peak) : {result['memory']['tracemalloc_peak_mb']} MB")
    ws = result['memory']['process_working_set_mb']
    print(f" memory (working set)      : {ws if ws is not None else 'n/a'} MB")
    print(f" evidence published        : {result['evidence_published']}")
    print("=" * 68)
    print(" NOTE: measured numbers on this machine - not extrapolated.\n")


if __name__ == "__main__":
    main()
