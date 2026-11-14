"""Shared pytest fixtures: deterministic stores, events and scenarios."""

from __future__ import annotations

from typing import Any

import pytest

from app.config import GraphConfig
from app.graph.builder import GraphBuilder
from app.graph.graph_store import GraphStore
from app.graph.models import TransactionEvent, TransactionStatus
from app.simulator.synthetic import SyntheticTransactionGenerator

# Fixed reference timeline so every test is deterministic.
T0 = 1_700_000_000.0


def make_event(
    tx: str,
    src: str,
    dst: str,
    amount: float = 1000.0,
    ts: float = T0,
    status: TransactionStatus = TransactionStatus.COMPLETED,
    event_type: str = "TRANSACTION",
    event_id: str | None = None,
) -> TransactionEvent:
    return TransactionEvent(
        event_id=event_id or f"EVT-{tx}",
        transaction_id=tx,
        source_account=src,
        destination_account=dst,
        amount=amount,
        timestamp=ts,
        status=status,
        event_type=event_type,
    )


@pytest.fixture()
def config() -> GraphConfig:
    return GraphConfig()


@pytest.fixture()
def store(config: GraphConfig) -> GraphStore:
    return GraphStore(config)


@pytest.fixture()
def builder(store: GraphStore) -> GraphBuilder:
    return GraphBuilder(store)


def ingest(store: GraphStore, events: list[TransactionEvent]) -> GraphStore:
    for event in events:
        store.add_event(event)
    return store


@pytest.fixture()
def fan_in_store(store: GraphStore) -> GraphStore:
    """10 distinct accounts pay ACC-TARGET within a 30s span."""
    events = []
    for i in range(10):
        events.append(
            make_event(f"FI-{i}", f"SRC-{i:02d}", "ACC-TARGET", amount=5000 + i * 100, ts=T0 + i * 3)
        )
    return ingest(store, events)


@pytest.fixture()
def fan_out_store(store: GraphStore) -> GraphStore:
    """ACC-SOURCE pays 10 distinct accounts within a 30s span."""
    events = []
    for i in range(10):
        events.append(
            make_event(f"FO-{i}", "ACC-SOURCE", f"DST-{i:02d}", amount=4000 + i * 50, ts=T0 + i * 3)
        )
    return ingest(store, events)


@pytest.fixture()
def cycle_store(store: GraphStore) -> GraphStore:
    """A -> B -> C -> A closed loop of settled transactions."""
    events = [
        make_event("CY-1", "ACC-A", "ACC-B", 10_000, T0),
        make_event("CY-2", "ACC-B", "ACC-C", 10_000, T0 + 5),
        make_event("CY-3", "ACC-C", "ACC-A", 10_000, T0 + 10),
    ]
    return ingest(store, events)


@pytest.fixture()
def chain_store(store: GraphStore) -> GraphStore:
    """Multi-hop: S1 -> S2 -> S3 -> S4 -> DEST."""
    events = [
        make_event("MH-1", "S1", "S2", 9000, T0),
        make_event("MH-2", "S2", "S3", 8500, T0 + 30),
        make_event("MH-3", "S3", "S4", 8000, T0 + 60),
        make_event("MH-4", "S4", "DEST", 7500, T0 + 90),
        # a decoy branch that should not be part of the main path
        make_event("MH-5", "S2", "DEAD-END", 500, T0 + 10),
    ]
    return ingest(store, events)


@pytest.fixture()
def mixed_store(store: GraphStore) -> GraphStore:
    """Mixed statuses: only COMPLETED must count as money movement."""
    events = [
        make_event("MX-OK", "U1", "U2", 1000, T0, TransactionStatus.COMPLETED),
        make_event("MX-PEND", "U3", "U4", 1000, T0 + 1, TransactionStatus.PENDING),
        make_event("MX-REJ", "U5", "U6", 1000, T0 + 2, TransactionStatus.REJECTED),
        make_event("MX-REV", "U7", "U8", 1000, T0 + 3, TransactionStatus.REVERSED),
        make_event("MX-HELD", "U9", "U10", 1000, T0 + 4, TransactionStatus.HELD_FOR_VERIFICATION),
    ]
    return ingest(store, events)


@pytest.fixture()
def synthetic() -> SyntheticTransactionGenerator:
    return SyntheticTransactionGenerator(seed=7, events_per_second=100.0, start_ts=T0)


def assert_valid_evidence(payload: dict[str, Any]) -> None:
    """Every referenced transaction id must exist in the payload structures."""
    assert payload["analysis_status"] in ("completed", "completed_partial", "account_not_found")
    for pattern in payload["detected_patterns"]:
        assert pattern["pattern_type"]
        assert pattern["pattern_id"]
        assert pattern["explanation"]
        assert isinstance(pattern["transaction_ids"], list)
