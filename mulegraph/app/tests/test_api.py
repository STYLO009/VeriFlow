"""API integration tests (FastAPI TestClient)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.graph.models import TransactionEvent
from app.main import create_app, create_services

# Anchor test data near "now" so preset windows (5m/24h) include it.
T0 = time.time() - 120.0


@pytest.fixture()
def client() -> TestClient:
    services = create_services()
    # seed a small scenario
    store = services["store"]
    events = [
        ("TX-1", "ACC-101", "ACC-102", 5000.0, T0),
        ("TX-2", "ACC-103", "ACC-101", 7000.0, T0 + 2),
        ("TX-3", "ACC-104", "ACC-101", 6000.0, T0 + 4),
        ("TX-4", "ACC-105", "ACC-101", 8000.0, T0 + 6),
        ("TX-5", "ACC-106", "ACC-101", 9000.0, T0 + 8),
        ("TX-6", "ACC-101", "ACC-107", 4000.0, T0 + 10),
        ("TX-7", "ACC-101", "ACC-108", 4500.0, T0 + 12),
        ("TX-8", "ACC-101", "ACC-109", 4700.0, T0 + 14),
        ("TX-9", "ACC-101", "ACC-110", 4900.0, T0 + 16),
        ("TX-10", "ACC-101", "ACC-111", 5100.0, T0 + 18),
        # cycle A -> B -> C -> A
        ("TX-11", "ACC-201", "ACC-202", 10000.0, T0 + 20),
        ("TX-12", "ACC-202", "ACC-203", 10000.0, T0 + 22),
        ("TX-13", "ACC-203", "ACC-201", 10000.0, T0 + 24),
    ]
    for tx, src, dst, amount, ts in events:
        store.add_event(
            TransactionEvent(
                event_id=f"EVT-{tx}",
                transaction_id=tx,
                source_account=src,
                destination_account=dst,
                amount=amount,
                timestamp=ts,
            )
        )
    app = create_app(services)
    with TestClient(app) as c:
        c._services = services  # type: ignore[attr-defined]
        yield c


def test_health(client: TestClient) -> None:
    resp = client.get("/api/v1/graph/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["nodes"] > 0
    assert body["edges"] == 13


def test_stats(client: TestClient) -> None:
    resp = client.get("/api/v1/graph/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["store"]["transactions"] == 13
    assert "5m" in body["windows"]
    assert body["profiles"] == ["FAST", "STANDARD", "DEEP"]


def test_analyze_endpoint(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/graph/analyze",
        json={"account_id": "ACC-101", "time_window": "24h", "profile": "STANDARD"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["analysis_status"] in ("completed", "completed_partial")
    assert body["target_account"] == "ACC-101"
    assert body["graph_summary"]["nodes"] >= 1
    assert body["graph_summary"]["incoming_transactions"] == 4
    assert body["graph_summary"]["outgoing_transactions"] == 6
    assert isinstance(body["detected_patterns"], list)
    assert isinstance(body["graph_evidence"], list)
    assert body["analysis_metadata"]["execution_time_ms"] > 0
    assert "fan_detection.detect_fan_in" in body["analysis_metadata"]["algorithms_executed"]
    # evidence must separate the three kinds
    kinds = {e["kind"] for e in body["graph_evidence"]}
    assert "GRAPH_FACT" in kinds
    assert "RISK_INTERPRETATION" in kinds
    # severity is one of the allowed values
    assert body["risk_assessment"]["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def test_analyze_unknown_account(client: TestClient) -> None:
    resp = client.post("/api/v1/graph/analyze", json={"account_id": "NOPE"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis_status"] == "account_not_found"


def test_analyze_validation_error(client: TestClient) -> None:
    resp = client.post("/api/v1/graph/analyze", json={"time_window": "5m"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_transaction_ingest_and_dedupe(client: TestClient) -> None:
    payload = {
        "event": {
            "event_id": "EVT-NEW-1",
            "transaction_id": "TX-NEW-1",
            "source_account": "ACC-301",
            "destination_account": "ACC-302",
            "amount": 1234.5,
            "timestamp": T0 + 100,
            "status": "COMPLETED",
        }
    }
    first = client.post("/api/v1/graph/transaction", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["accepted"] == 1

    second = client.post("/api/v1/graph/transaction", json=payload)
    assert second.status_code == 200
    assert second.json()["duplicates"] == 1
    assert second.json()["accepted"] == 0

    batch = client.post(
        "/api/v1/graph/transaction",
        json={
            "events": [
                {
                    "event_id": f"EVT-B-{i}",
                    "transaction_id": f"TX-B-{i}",
                    "source_account": "ACC-303",
                    "destination_account": "ACC-304",
                    "amount": 100,
                    "timestamp": T0 + 200 + i,
                }
                for i in range(5)
            ]
        },
    )
    assert batch.json()["processed"] == 5
    assert batch.json()["accepted"] == 5


def test_transaction_invalid_amount(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/graph/transaction",
        json={
            "event": {
                "event_id": "EVT-BAD",
                "transaction_id": "TX-BAD",
                "source_account": "A",
                "destination_account": "B",
                "amount": -5,
                "timestamp": T0,
            }
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_account_endpoints(client: TestClient) -> None:
    resp = client.get("/api/v1/graph/account/ACC-101", params={"window": "24h"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["exists"] is True
    assert body["degrees"]["in_degree"] == 4
    assert body["settled_amount"] > 0

    missing = client.get("/api/v1/graph/account/UNKNOWN", params={"window": "24h"})
    assert missing.status_code == 200
    assert missing.json()["exists"] is False

    nb = client.get("/api/v1/graph/account/ACC-101/neighborhood", params={"hops": 1, "window": "24h"})
    assert nb.status_code == 200
    assert nb.json()["node_count"] >= 6
    assert nb.json()["edge_count"] == 10

    nb_missing = client.get("/api/v1/graph/account/NOBODY/neighborhood")
    assert nb_missing.status_code == 404
    assert nb_missing.json()["error"]["code"] == "NOT_FOUND"


def test_patterns_endpoint_paginated(client: TestClient) -> None:
    resp = client.get(
        "/api/v1/graph/account/ACC-101/patterns",
        params={"window": "24h", "profile": "STANDARD", "page": 1, "page_size": 2},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pattern_count"] >= 1
    assert len(body["patterns"]) <= 2
    assert body["page"] == 1
    assert body["total_pages"] >= 1
    assert body["risk_assessment"]["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def test_trace_endpoint(client: TestClient) -> None:
    resp = client.get(
        "/api/v1/graph/trace/ACC-103/ACC-101",
        params={"max_hops": 3, "window": "24h"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["path_count"] >= 1
    assert body["paths"][0]["hop_count"] == 1
    assert body["paths"][0]["hops"][0]["transaction_id"] == "TX-2"


def test_cycles_endpoint(client: TestClient) -> None:
    resp = client.get("/api/v1/graph/cycles", params={"window": "24h", "min_length": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["cycle_count"] >= 1
    cycle = body["cycles"][0]
    assert set(cycle["transaction_ids"]) == {"TX-11", "TX-12", "TX-13"}
    assert cycle["total_amount"] == 30000


def test_communities_endpoint(client: TestClient) -> None:
    resp = client.get("/api/v1/graph/communities", params={"window": "24h", "min_size": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["community_count"] >= 1
    assert body["algorithm"] in ("louvain", "connected_components")


def test_metrics_endpoint(client: TestClient) -> None:
    resp = client.get("/api/v1/graph/metrics", params={"window": "24h"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["accounts_measured"] > 0
    assert "ACC-101" in body["metrics"]

    scoped = client.get("/api/v1/graph/metrics", params={"window": "24h", "account_id": "ACC-101"})
    assert scoped.status_code == 200
    assert "ACC-101" in scoped.json()["metrics"]


def test_unknown_route_structured_error(client: TestClient) -> None:
    resp = client.get("/api/v1/graph/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "HTTP_404"


def test_empty_ingest_is_bad_request(client: TestClient) -> None:
    """An empty payload must be a structured 400, never a 500."""
    resp = client.post("/api/v1/graph/transaction", json={})
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "GRAPH_ERROR"
    assert "no events" in body["error"]["message"]


def test_root_and_health_alias(client: TestClient) -> None:
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["health"] == "/health"

    alias = client.get("/health")
    assert alias.status_code == 200
    body = alias.json()
    assert body["status"] == "healthy"
    assert body["edges"] == 13
    # identical payload to the versioned endpoint
    canonical = client.get("/api/v1/graph/health").json()
    assert body == canonical


def test_bad_window_structured_error(client: TestClient) -> None:
    resp = client.get("/api/v1/graph/account/ACC-101", params={"window": "3d"})
    assert resp.status_code in (400, 422)
    assert "error" in resp.json()
