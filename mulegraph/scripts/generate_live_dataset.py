"""Generate a replayable live-demo transaction dataset.

The output is accepted directly by ``POST /api/v1/graph/transaction``:

    python scripts/generate_live_dataset.py
    curl -X POST http://127.0.0.1:8000/api/v1/graph/transaction \
      -H "content-type: application/json" --data-binary @data/live_demo_events.json
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def build_events() -> list[dict]:
    """Build a compact scenario that demonstrates each graph signal."""
    anchor = time.time() - 240.0
    batch_date = time.strftime("%Y%m%d")
    events: list[dict] = []
    sequence = 0

    def add(source: str, destination: str, amount: float, offset: float, status: str = "COMPLETED") -> None:
        nonlocal sequence
        sequence += 1
        events.append(
            {
                "event_id": f"evt_{batch_date}_{sequence:04d}",
                "transaction_id": f"UPI{batch_date}{sequence:06d}",
                "source_account": source,
                "destination_account": destination,
                "amount": amount,
                "currency": "INR",
                "timestamp": round(anchor + offset, 3),
                "status": status,
            }
        )

    # Fan-in: many sources converge on one account.
    fan_in_sources = [
        "arjun.mehta@oksbi", "priya.nair@okhdfcbank", "sanjay.rao@okaxis",
        "meera.iyer@okicici", "vikram.shah@oksbi", "isha.kapoor@okhdfcbank",
        "rohit.bose@okaxis", "tanvi.gupta@okicici",
    ]
    hub = "sharma.traders@okaxis"
    for index, source in enumerate(fan_in_sources):
        add(source, hub, 12_000 + index * 750, index * 3)

    # Fan-out: the hub distributes funds quickly to many accounts.
    fan_out_destinations = [
        "kavya.retail@okicici", "mohit.verma@oksbi", "aditi.malhotra@okhdfcbank",
        "neeraj.khan@okaxis", "simran.kaur@okicici", "deepak.yadav@oksbi",
        "nisha.patel@okhdfcbank", "manish.jain@okaxis",
    ]
    for index, destination in enumerate(fan_out_destinations):
        add(hub, destination, 13_000 + index * 500, 28 + index * 3)

    # Two circular flows.
    for repetition in range(2):
        offset = 60 + repetition * 22
        add("amit.joshi@okaxis", "neha.kapoor@oksbi", 50_000, offset)
        add("neha.kapoor@oksbi", "rohan.singh@okhdfcbank", 50_000, offset + 2)
        add("rohan.singh@okhdfcbank", "amit.joshi@okaxis", 50_000, offset + 4)

    # Multi-hop chain.
    add("sneha.das@oksbi", "kiran.logistics@okicici", 90_000, 112)
    add("kiran.logistics@okicici", "omkar.wholesale@okaxis", 88_000, 115)
    add("omkar.wholesale@okaxis", "farah.exports@okhdfcbank", 86_000, 118)
    add("farah.exports@okhdfcbank", "dev.industries@oksbi", 84_000, 121)

    # Non-settled events demonstrate that held/rejected money is excluded from flow risk.
    add("pallavi.sen@okicici", hub, 99_000, 125, "HELD_FOR_VERIFICATION")
    add("abhay.mishra@okaxis", hub, 99_000, 126, "REJECTED")

    # Ordinary background traffic gives the live view realistic context.
    normal_pairs = [
        ("anuj.agarwal@oksbi", "shreya.roy@okicici"), ("rahul.chopra@okaxis", "pihu.menon@oksbi"),
        ("sahil.tiwari@okhdfcbank", "rhea.bhat@okaxis"), ("manav.sethi@okicici", "kriti.rao@oksbi"),
        ("yash.thakur@okaxis", "mansi.goyal@okhdfcbank"), ("nikhil.arora@oksbi", "diya.bansal@okicici"),
        ("tarun.kohli@okhdfcbank", "riya.dutta@okaxis"), ("varun.singh@okicici", "aanya.puri@oksbi"),
        ("suresh.pillai@okaxis", "lavanya.murthy@okhdfcbank"), ("gautam.ahuja@oksbi", "sakshi.wadhwa@okicici"),
        ("abhishek.paul@okhdfcbank", "sonal.banerjee@okaxis"), ("harsh.vora@okicici", "mitali.desai@oksbi"),
        ("vivek.nanda@okaxis", "pooja.rastogi@okhdfcbank"), ("akshay.bedi@oksbi", "nupur.sethi@okicici"),
        ("rakesh.dubey@okhdfcbank", "komal.suri@okaxis"), ("ayush.jain@okicici", "palak.garg@oksbi"),
        ("sameer.kulkarni@okaxis", "shruti.rao@okhdfcbank"), ("alok.malviya@oksbi", "preeti.nair@okicici"),
        ("nitin.modi@okhdfcbank", "kajal.mehta@okaxis"), ("devika.rao@okicici", "arpit.sharma@oksbi"),
    ]
    for index, (source, destination) in enumerate(normal_pairs):
        add(source, destination, 500 + index * 25, 8 + index * 2)

    return events


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the Hackmatrix live-demo dataset")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "live_demo_events.json",
        help="output JSON path",
    )
    args = parser.parse_args()
    events = build_events()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"events": events}, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(events)} events to {args.out}")


if __name__ == "__main__":
    main()
