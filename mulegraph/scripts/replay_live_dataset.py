"""Replay the live-demo dataset against the running graph API."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay synthetic transactions at a visible rate")
    parser.add_argument("--file", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "live_demo_events.json")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--tps", type=float, default=5.0, help="events per second")
    args = parser.parse_args()

    events = json.loads(args.file.read_text(encoding="utf-8"))["events"]
    interval = 1.0 / max(args.tps, 0.1)
    accepted = 0
    duplicates = 0

    with httpx.Client(base_url=args.base, timeout=30.0) as client:
        for index, event in enumerate(events, start=1):
            response = client.post("/api/v1/graph/transaction", json={"event": event})
            response.raise_for_status()
            result = response.json()
            accepted += result["accepted"]
            duplicates += result["duplicates"]
            action = result["results"][0]["action"]
            print(f"{index:03d}/{len(events)} {event['transaction_id']} action={action} graph_version={result['graph_version']}", flush=True)
            time.sleep(interval)

    print(f"completed events={len(events)} accepted={accepted} duplicates={duplicates}")


if __name__ == "__main__":
    main()
