"""Regression coverage against the checked-in PaySim-derived dataset."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.dataset import DEFAULT_DATASET_PATH, read_dataset
from app.main import app, create_app, create_services


def test_current_dataset_has_100_valid_events() -> None:
    events = read_dataset(DEFAULT_DATASET_PATH)

    assert len(events) == 100
    assert len({event.event_id for event in events}) == 100
    assert len({event.transaction_id for event in events}) == 100
    assert {event.currency for event in events} == {"USD"}
    assert sum(event.metadata["is_fraud"] for event in events) == 2


def test_api_ingests_current_dataset_and_returns_consistent_results() -> None:
    payload = json.loads(Path(DEFAULT_DATASET_PATH).read_text(encoding="utf-8"))
    services = create_services()

    with TestClient(create_app(services)) as client:
        response = client.post("/api/v1/graph/transaction", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "accepted"
        assert body["processed"] == 100
        assert body["accepted"] == 100
        assert body["duplicates"] == 0
        assert body["graph_version"] == 100

        stats = client.get("/api/v1/graph/stats").json()
        assert stats["store"]["transactions"] == 100
        assert stats["store"]["edges"] == 100
        assert stats["store"]["unique_events"] == 100
        assert stats["events_processed"] == 100

        first = payload["events"][0]
        account = client.get(
            f"/api/v1/graph/account/{first['source_account']}",
            params={"window": "24h"},
        )
        assert account.status_code == 200, account.text
        assert account.json()["exists"] is True
        assert account.json()["transaction_count"] == 1
        assert account.json()["settled_amount"] == first["amount"]

        duplicate = client.post("/api/v1/graph/transaction", json=payload)
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["accepted"] == 0
        assert duplicate.json()["duplicates"] == 100


def test_live_graph_endpoint_matches_current_dataset() -> None:
    source = read_dataset(DEFAULT_DATASET_PATH)
    with TestClient(app) as client:
        response = client.get("/api/v1/graph/transactions?page=1&page_size=100")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert response.json()["total"] == len(source)
    assert {item["transactionRef"] for item in items} == {event.transaction_id for event in source}
    first = next(item for item in items if item["transactionRef"] == source[0].transaction_id)
    assert first["sender"]["accountRef"] == source[0].source_account
    assert first["receiver"]["accountRef"] == source[0].destination_account

