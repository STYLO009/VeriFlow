"""Local synthetic streaming demo (no broker required).

Feeds deterministic synthetic transactions through the streaming pipeline and
prints the structured graph evidence that would be published downstream.

Usage (PowerShell):
    .\\.venv\\Scripts\\python.exe scripts\\run_simulator.py --events 500 --tps 50
    .\\.venv\\Scripts\\python.exe scripts\\run_simulator.py --events 200 --json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.graph.builder import GraphBuilder  # noqa: E402
from app.graph.graph_store import GraphStore  # noqa: E402
from app.simulator.synthetic import SyntheticTransactionGenerator  # noqa: E402
from app.streaming.event_processor import CollectingSink, GraphEventProcessor  # noqa: E402
from app.streaming.consumer import ListEventSource, run_stream  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="MuleGraph synthetic stream demo")
    parser.add_argument("--events", type=int, default=500, help="number of events")
    parser.add_argument("--tps", type=float, default=50.0, help="events per second")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--json", action="store_true", help="print evidence payloads as JSON")
    parser.add_argument("--show", type=int, default=3, help="number of evidence payloads to show")
    args = parser.parse_args()

    store = GraphStore()
    sink = CollectingSink()
    processor = GraphEventProcessor(GraphBuilder(store), store, sink=sink)
    generator = SyntheticTransactionGenerator(seed=args.seed, events_per_second=args.tps)

    events = list(generator.generate(args.events))
    stats = run_stream(ListEventSource(events), processor, batch_size=50, max_events=args.events)

    print()
    print("=" * 68)
    print(f" Synthetic stream: {stats['events']} events, "
          f"{stats['events_per_second']} events/s (simulated {args.tps} TPS)")
    print(f" Graph: {store.stats()['nodes']} nodes / {store.stats()['edges']} edges")
    print(f" Evidence payloads published: {processor.stats()['published']}")
    print("=" * 68)

    if args.json:
        print(json.dumps(sink.latest(args.show), indent=2, default=str))
        return

    for payload in sink.latest(args.show):
        analysis = payload["analysis"]
        print()
        print(f"-- {payload['event_id']} -> {payload['transaction_id']} "
              f"(graph v{payload['graph_version']}, {payload['processing_latency_ms']} ms)")
        print(f"   fan-in detected : {analysis['fan_in']['detected']} "
              f"({analysis['fan_in']['unique_accounts']} unique sources)")
        print(f"   fan-out detected: {analysis['fan_out']['detected']} "
              f"({analysis['fan_out']['unique_accounts']} unique destinations)")
        print(f"   risk            : {analysis['risk_assessment']['severity']} "
              f"score={analysis['risk_assessment']['score']}")
        print(f"   window counts   : {analysis['window_counts']}")
        for evidence in analysis["graph_evidence"][:2]:
            print(f"   evidence [{evidence['kind']}] {evidence['label']}: {evidence['explanation'][:110]}")
    print()


if __name__ == "__main__":
    main()
