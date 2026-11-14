"""Seed the running API with a demo scenario and capture real responses.

Run the server first:
    .\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8017
Then:
    .\\.venv\\Scripts\\python.exe scripts\\capture_examples.py

Writes docs/example_responses/*.json with *actual* API output.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = "http://127.0.0.1:8017"
# anchor all demo events inside the last 5 minutes so preset windows include them
T0 = time.time() - 150.0


def demo_events() -> list[dict]:
    events: list[dict] = []
    n = 0

    def add(src: str, dst: str, amount: float, offset: float, status: str = "COMPLETED") -> None:
        nonlocal n
        n += 1
        events.append(
            {
                "event_id": f"EVT-DEMO-{n}",
                "transaction_id": f"TX-DEMO-{n}",
                "source_account": src,
                "destination_account": dst,
                "amount": amount,
                "timestamp": round(T0 + offset, 3),
                "status": status,
            }
        )

    # fan-in: 7 distinct accounts pay ACC-9001 within ~30s
    for i in range(7):
        add(f"ACC-81{i:02d}", "ACC-9001", 12_000 + i * 750, i * 4)
    # fan-out: ACC-9001 distributes to 6 destinations quickly
    for i in range(6):
        add("ACC-9001", f"ACC-82{i:02d}", 13_000 + i * 500, 34 + i * 4)
    # circular flow: ACC-7001 -> ACC-7002 -> ACC-7003 -> ACC-7001 (twice)
    for rep in range(2):
        base = 70 + rep * 25
        add("ACC-7001", "ACC-7002", 50_000, base)
        add("ACC-7002", "ACC-7003", 50_000, base + 3)
        add("ACC-7003", "ACC-7001", 50_000, base + 6)
    # multi-hop: ACC-6001 -> ACC-6002 -> ACC-6003 -> ACC-6004
    add("ACC-6001", "ACC-6002", 90_000, 130)
    add("ACC-6002", "ACC-6003", 88_000, 134)
    add("ACC-6003", "ACC-6004", 86_000, 138)
    # non-settled noise (must not count as money movement)
    add("ACC-8300", "ACC-9001", 99_000, 140, status="HELD_FOR_VERIFICATION")
    add("ACC-8301", "ACC-9001", 99_000, 141, status="REJECTED")
    # ordinary traffic
    for i in range(20):
        add(f"ACC-84{i:02d}", f"ACC-85{i:02d}", 500 + i * 25, 5 + i * 3)
    return events


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "docs" / "example_responses"))
    args = parser.parse_args()

    client = httpx.Client(base_url=args.base, timeout=30.0)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) ingest the scenario
    events = demo_events()
    resp = client.post("/api/v1/graph/transaction", json={"events": events})
    resp.raise_for_status()
    ingest = resp.json()
    print(f"ingested: accepted={ingest['accepted']} duplicates={ingest['duplicates']}")

    # 2) capture example responses
    captures: dict[str, tuple[str, dict | None]] = {
        "analyze_fanin": (
            "POST",
            {"path": "/api/v1/graph/analyze",
             "json": {"account_id": "ACC-9001", "time_window": "5m", "profile": "STANDARD"}},
        ),
        "analyze_fast": (
            "POST",
            {"path": "/api/v1/graph/analyze",
             "json": {"account_id": "ACC-7001", "time_window": "5m", "profile": "FAST"}},
        ),
        "account": ("GET", {"path": "/api/v1/graph/account/ACC-9001", "params": {"window": "5m"}}),
        "neighborhood": (
            "GET",
            {"path": "/api/v1/graph/account/ACC-7001/neighborhood",
             "params": {"hops": 1, "window": "5m"}},
        ),
        "patterns": (
            "GET",
            {"path": "/api/v1/graph/account/ACC-9001/patterns",
             "params": {"window": "5m", "profile": "STANDARD"}},
        ),
        "trace": (
            "GET",
            {"path": "/api/v1/graph/trace/ACC-6001/ACC-6004",
             "params": {"max_hops": 4, "window": "5m"}},
        ),
        "cycles": ("GET", {"path": "/api/v1/graph/cycles", "params": {"window": "5m"}}),
        "communities": ("GET", {"path": "/api/v1/graph/communities", "params": {"window": "5m"}}),
        "metrics": ("GET", {"path": "/api/v1/graph/metrics", "params": {"window": "5m"}}),
        "health": ("GET", {"path": "/api/v1/graph/health"}),
        "stats": ("GET", {"path": "/api/v1/graph/stats"}),
    }

    saved: dict[str, dict] = {}
    for name, (method, spec) in captures.items():
        if method == "POST":
            r = client.post(spec["path"], json=spec["json"])
        else:
            r = client.get(spec["path"], params=spec.get("params"))
        r.raise_for_status()
        body = r.json()
        saved[name] = body
        (out_dir / f"{name}.json").write_text(json.dumps(body, indent=2), encoding="utf-8")
        print(f"captured {name}: HTTP {r.status_code}")

    (out_dir / "ingest_transaction.json").write_text(json.dumps(ingest, indent=2), encoding="utf-8")

    # 3) a compact error example too
    bad = client.post("/api/v1/graph/analyze", json={"time_window": "5m"})
    (out_dir / "error_validation.json").write_text(json.dumps(bad.json(), indent=2), encoding="utf-8")
    print(f"\nwrote examples to {out_dir}")

    # quick sanity printout used in the README
    analyze = saved["analyze_fanin"]
    print(f"\nanalyze: status={analyze['analysis_status']} "
          f"patterns={len(analyze['detected_patterns'])} "
          f"severity={analyze['risk_assessment']['severity']} "
          f"evidence_items={len(analyze['graph_evidence'])}")
    for p in analyze["detected_patterns"]:
        print(f"  - {p['pattern_type']} ({p['severity']}): {p['explanation'][:100]}")


if __name__ == "__main__":
    main()
