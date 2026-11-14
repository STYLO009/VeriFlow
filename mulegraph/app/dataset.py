"""Loading and ingesting the checked-in MuleGraph event dataset."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .graph.models import TransactionEvent


DEFAULT_DATASET_PATH = Path(__file__).resolve().parents[1] / "data" / "live_demo_events.json"


def read_dataset(path: str | Path = DEFAULT_DATASET_PATH) -> list[TransactionEvent]:
    """Read the wrapped JSON event dataset and validate every event."""
    dataset_path = Path(path)
    payload: Any = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValueError(f"dataset {dataset_path} must contain an 'events' list")
    return [TransactionEvent.model_validate(item) for item in payload["events"]]


def ingest_dataset(services: dict[str, Any], path: str | Path = DEFAULT_DATASET_PATH) -> dict[str, int | str]:
    """Ingest a dataset through the same processing path as the HTTP API."""
    events = read_dataset(path)
    processor = services["processor"]
    repository = services["repository"]
    accepted = 0
    duplicates = 0

    for event in events:
        result = processor.process(event)
        if result.accepted:
            repository.append(event)
            accepted += 1
        elif result.action == "duplicate":
            duplicates += 1

    return {
        "path": str(Path(path)),
        "processed": len(events),
        "accepted": accepted,
        "duplicates": duplicates,
    }

