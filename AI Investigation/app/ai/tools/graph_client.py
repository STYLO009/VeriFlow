"""Read-only clients for the MuleGraph graph engine APIs.

The AI layer never talks to graph internals directly: it goes through this
client so every investigation tool maps onto an existing engine capability
(the same functions behind ``/api/v1/graph/*``).

* ``InProcessGraphClient`` - default; uses the shared service container the
  FastAPI app assembles in ``app/main.py`` (identical to the REST handlers).
* ``HttpGraphClient`` - used when ``MULEGRAPH_AI_GRAPH_API_URL`` is set, so
  the AI layer can run beside a *separate* graph-engine deployment and call
  its REST API as external tools.

Both are strictly read-only: no method mutates graph state.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .validation import (
    ToolExecutionError,
    ToolValidationError,
    validate_account_id,
    validate_int,
    validate_profile,
    validate_transaction_id,
    validate_window,
)

logger = logging.getLogger("mulegraph.ai.tools")


class GraphClient:
    """Interface for read-only graph investigation queries."""

    backend = "abstract"

    # --- operational ---------------------------------------------------
    def health(self) -> dict[str, Any]:  # pragma: no cover - interface
        raise NotImplementedError

    def stats(self) -> dict[str, Any]:  # pragma: no cover - interface
        raise NotImplementedError

    def graph_version(self) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    # --- account / transaction views ------------------------------------
    def account_exists(self, account_id: str) -> bool:  # pragma: no cover
        raise NotImplementedError

    def account_profile(self, account_id: str, window: str) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def neighborhood(self, account_id: str, hops: int, window: str) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def transaction_history(
        self, account_id: str, window: str, page: int, page_size: int
    ) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def transaction_details(self, transaction_id: str) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    # --- pattern detectors ----------------------------------------------
    def detect_fan(self, account_id: str, window: str, direction: str) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def trace(
        self,
        source: str,
        destination: str,
        max_hops: int,
        window: str,
        min_amount: float | None,
        chronological: bool,
        shortest_only: bool,
    ) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def cycles(
        self, window: str, min_length: int, max_length: int | None, account_id: str | None
    ) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def temporal_patterns(self, account_id: str, window: str) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def communities(self, account_id: str, window: str, min_size: int) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def centrality(self, account_id: str, window: str) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def graph_evidence(
        self, account_id: str, window: str, profile: str
    ) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def close(self) -> None:
        return None


# ====================================================================== #
# in-process backend (same code paths as the REST handlers)
# ====================================================================== #
class InProcessGraphClient(GraphClient):
    backend = "in-process"

    def __init__(self, services: dict[str, Any]) -> None:
        self._services = services

    # --- helpers --------------------------------------------------------
    @property
    def _store(self):  # type: ignore[no-untyped-def]
        return self._services["store"]

    @property
    def _analyzer(self):  # type: ignore[no-untyped-def]
        return self._services["analyzer"]

    @staticmethod
    def _window(name: str) -> Window:
        # Keep the graph engine dependency inside the optional in-process
        # adapter. The standalone AI service only needs HttpGraphClient.
        from ...graph.adjacency_index import Window

        return Window.preset(name)

    # --- operational ----------------------------------------------------
    def health(self) -> dict[str, Any]:
        return self._analyzer.health()

    def stats(self) -> dict[str, Any]:
        return self._store.stats()

    def graph_version(self) -> int:
        return int(self._store.version)

    # --- account / transaction ------------------------------------------
    def account_exists(self, account_id: str) -> bool:
        return bool(self._store.has_account(account_id))

    def account_profile(self, account_id: str, window: str) -> dict[str, Any]:
        account_id = validate_account_id(account_id)
        window = validate_window(window)
        resolved = self._window(window)
        store = self._store
        exists = store.has_account(account_id)
        data = store.graph.nodes.get(account_id, {})
        records = store.transactions_for_account(account_id, resolved) if exists else []
        settled = [r for r in records if r.is_settled]
        return {
            "account_id": account_id,
            "exists": exists,
            "window": window,
            "first_seen": data.get("first_seen"),
            "last_seen": data.get("last_seen"),
            "degrees": store.degrees(account_id, resolved) if exists else {},
            "activity": (
                self._services["temporal"].account_activity(account_id, resolved)
                if exists
                else {}
            ),
            "transaction_count": len(records),
            "settled_amount": round(sum(r.amount for r in settled), 2),
            "graph_version": store.version,
        }

    def neighborhood(self, account_id: str, hops: int, window: str) -> dict[str, Any]:
        from ...intelligence.subgraph_extractor import extract_subgraph

        account_id = validate_account_id(account_id)
        hops = validate_int(hops, "hops", minimum=1, maximum=4, default=1)
        window = validate_window(window)
        if not self._store.has_account(account_id):
            raise ToolExecutionError(f"account {account_id} not found in graph")
        view = extract_subgraph(
            self._store, account_id, hops=hops, window=self._window(window)
        )
        payload = view.to_dict()
        return {
            "account_id": account_id,
            "hops": hops,
            "time_window": window,
            "node_count": payload["node_count"],
            "edge_count": payload["edge_count"],
            "truncated": payload["truncated"],
            "nodes": payload["nodes"],
            "edges": payload["edges"],
        }

    def transaction_history(
        self, account_id: str, window: str, page: int, page_size: int
    ) -> dict[str, Any]:
        account_id = validate_account_id(account_id)
        window = validate_window(window)
        page = validate_int(page, "page", minimum=1, maximum=10_000, default=1)
        page_size = validate_int(page_size, "page_size", minimum=1, maximum=100, default=50)
        if not self._store.has_account(account_id):
            raise ToolExecutionError(f"account {account_id} not found in graph")
        resolved = self._window(window)
        records = self._store.transactions_for_account(account_id, resolved)
        start = (page - 1) * page_size
        page_items = records[start : start + page_size]
        settled = [r for r in records if r.is_settled]
        return {
            "account_id": account_id,
            "window": window,
            "page": page,
            "page_size": page_size,
            "total_transactions": len(records),
            "total_pages": max(1, (len(records) + page_size - 1) // page_size),
            "settled_amount": round(sum(r.amount for r in settled), 2),
            "degrees": self._store.degrees(account_id, resolved),
            "transactions": [r.to_dict() for r in page_items],
        }

    def transaction_details(self, transaction_id: str) -> dict[str, Any]:
        transaction_id = validate_transaction_id(transaction_id)
        record = self._store.get_transaction(transaction_id)
        if record is None:
            raise ToolExecutionError(f"transaction {transaction_id} not found in graph")
        payload = record.to_dict()
        payload["graph_version"] = self._store.version
        return payload

    # --- pattern detectors ----------------------------------------------
    def detect_fan(self, account_id: str, window: str, direction: str) -> dict[str, Any]:
        from ...algorithms.fan_detection import detect_fan_in, detect_fan_out

        account_id = validate_account_id(account_id)
        window = validate_window(window)
        direction = str(direction).upper()
        if direction not in ("IN", "OUT"):
            raise ToolValidationError("direction", "must be 'IN' or 'OUT'")
        if not self._store.has_account(account_id):
            raise ToolExecutionError(f"account {account_id} not found in graph")
        resolved = self._window(window)
        fn = detect_fan_in if direction == "IN" else detect_fan_out
        result = fn(self._store, account_id, resolved)
        payload = result.to_dict()
        # keep transaction/counterparty references for evidence provenance
        payload["transaction_ids"] = list(result.transaction_ids)
        payload["counterparty_accounts"] = list(result.counterparty_accounts)
        payload["window_preset"] = window
        return payload

    def trace(
        self,
        source: str,
        destination: str,
        max_hops: int,
        window: str,
        min_amount: float | None,
        chronological: bool,
        shortest_only: bool,
    ) -> dict[str, Any]:
        from ...algorithms.multi_hop import trace_money_flow

        source = validate_account_id(source, "source")
        destination = validate_account_id(destination, "destination")
        max_hops = validate_int(max_hops, "max_hops", minimum=1, maximum=6, default=4)
        window = validate_window(window, default="24h")
        if min_amount is not None:
            min_amount = float(min_amount)
            if min_amount <= 0:
                raise ToolValidationError("min_amount", "must be > 0")
        result = trace_money_flow(
            self._store,
            source,
            destination,
            max_hops=max_hops,
            window=self._window(window),
            min_amount=min_amount,
            shortest_only=bool(shortest_only),
            strict_chronological=bool(chronological),
        )
        return result.to_dict()

    def cycles(
        self, window: str, min_length: int, max_length: int | None, account_id: str | None
    ) -> dict[str, Any]:
        from ...algorithms.cycle_detection import find_cycles

        window = validate_window(window, default="24h")
        min_length = validate_int(min_length, "min_length", minimum=2, maximum=8, default=3)
        if max_length is not None:
            max_length = validate_int(max_length, "max_length", minimum=3, maximum=8)
            if max_length < min_length:
                raise ToolValidationError("max_length", "must be >= min_length")
        if account_id:
            account_id = validate_account_id(account_id)
        scan = find_cycles(
            self._store,
            window=self._window(window),
            min_length=min_length,
            max_length=max_length,
        )
        payload = scan.to_dict()
        if account_id:
            matching = [c for c in payload.get("cycles", []) if account_id in c.get("accounts", [])]
            repeated = [
                r
                for r in payload.get("repeated_activity", [])
                if account_id in r.get("accounts", [])
            ]
            return {
                **payload,
                "account_filter": account_id,
                "total_cycles_in_window": payload.get("cycle_count", 0),
                "cycle_count": len(matching),
                "cycles": matching,
                "repeated_activity": repeated,
            }
        return payload

    def temporal_patterns(self, account_id: str, window: str) -> dict[str, Any]:
        from ...algorithms.temporal_motifs import detect_temporal_motifs

        account_id = validate_account_id(account_id)
        window = validate_window(window, default="24h")
        if not self._store.has_account(account_id):
            raise ToolExecutionError(f"account {account_id} not found in graph")
        scan = detect_temporal_motifs(self._store, window=self._window(window))
        payload = scan.to_dict()
        motifs = payload.get("motifs", [])
        matching = [
            m
            for m in motifs
            if account_id in (m.get("accounts_involved") or m.get("accounts") or [])
        ]
        return {
            "account_id": account_id,
            "time_window": window,
            "total_motifs_in_window": payload.get("motif_count", 0),
            "motif_count": len(matching),
            "motifs": matching,
            "detection_parameters": payload.get("detection_parameters", {}),
        }

    def communities(self, account_id: str, window: str, min_size: int) -> dict[str, Any]:
        from ...algorithms.community_detection import detect_communities

        account_id = validate_account_id(account_id)
        window = validate_window(window, default="24h")
        min_size = validate_int(min_size, "min_size", minimum=2, maximum=50, default=3)
        scan = detect_communities(
            self._store, window=self._window(window), min_size=min_size
        )
        payload = scan.to_dict()
        communities = payload.get("communities", [])
        membership = [c for c in communities if account_id in c.get("members", [])]
        top = sorted(communities, key=lambda c: c.get("size", 0), reverse=True)[:5]
        return {
            "account_id": account_id,
            "time_window": window,
            "algorithm": payload.get("algorithm"),
            "community_count": payload.get("community_count", 0),
            "account_communities": membership,
            "top_communities": top,
        }

    def centrality(self, account_id: str, window: str) -> dict[str, Any]:
        from ...algorithms.centrality import compute_centrality

        account_id = validate_account_id(account_id)
        window = validate_window(window, default="24h")
        scan = compute_centrality(self._store, window=self._window(window))
        payload = scan.to_dict(include_all=False)
        metrics = scan.for_account(account_id)
        return {
            "account_id": account_id,
            "time_window": window,
            "account_metrics": metrics,
            "is_bridge_node": account_id in (payload.get("bridge_nodes") or []),
            "bridge_nodes": payload.get("bridge_nodes", []),
            "top_pagerank": payload.get("top_pagerank", [])[:10],
            "top_betweenness": payload.get("top_betweenness", [])[:10],
            "parameters": payload.get("parameters", {}),
        }

    def graph_evidence(self, account_id: str, window: str, profile: str) -> dict[str, Any]:
        account_id = validate_account_id(account_id)
        window = validate_window(window, default="24h")
        profile = validate_profile(profile, default="FAST")
        result = self._analyzer.analyze_account(
            account_id, window=window, profile=profile, include_subgraph=False
        )
        payload = result.to_dict()
        payload.pop("subgraph", None)
        return payload


# ====================================================================== #
# HTTP backend (calls the graph engine's own REST API as external tools)
# ====================================================================== #
class HttpGraphClient(GraphClient):
    backend = "http"

    def __init__(self, base_url: str, timeout_s: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout_s)

    def close(self) -> None:
        self._client.close()

    # --- helpers --------------------------------------------------------
    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            resp = self._client.get(path, params=params or {})
        except httpx.TimeoutException as exc:
            raise ToolExecutionError(f"graph API timeout on {path}") from exc
        except httpx.HTTPError as exc:
            raise ToolExecutionError(f"graph API unreachable: {exc}") from exc
        if resp.status_code == 404:
            raise ToolExecutionError(f"graph API 404 on {path}: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise ToolExecutionError(
                f"graph API error {resp.status_code} on {path}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise ToolExecutionError(f"graph API returned non-JSON on {path}") from exc

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = self._client.post(path, json=body)
        except httpx.TimeoutException as exc:
            raise ToolExecutionError(f"graph API timeout on {path}") from exc
        except httpx.HTTPError as exc:
            raise ToolExecutionError(f"graph API unreachable: {exc}") from exc
        if resp.status_code >= 400:
            raise ToolExecutionError(
                f"graph API error {resp.status_code} on {path}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise ToolExecutionError(f"graph API returned non-JSON on {path}") from exc

    # --- operational ----------------------------------------------------
    def health(self) -> dict[str, Any]:
        return self._get("/api/v1/graph/health")

    def stats(self) -> dict[str, Any]:
        return self._get("/api/v1/graph/stats")

    def graph_version(self) -> int:
        try:
            return int(self.health().get("graph_version", 0))
        except (ToolExecutionError, TypeError, ValueError):  # pragma: no cover
            return 0

    # --- account / transaction ------------------------------------------
    def account_exists(self, account_id: str) -> bool:
        account_id = validate_account_id(account_id)
        try:
            return bool(self._get(f"/api/v1/graph/account/{account_id}").get("exists"))
        except ToolExecutionError:
            return False

    def account_profile(self, account_id: str, window: str) -> dict[str, Any]:
        account_id = validate_account_id(account_id)
        window = validate_window(window)
        return self._get(f"/api/v1/graph/account/{account_id}", {"window": window})

    def neighborhood(self, account_id: str, hops: int, window: str) -> dict[str, Any]:
        account_id = validate_account_id(account_id)
        hops = validate_int(hops, "hops", minimum=1, maximum=4, default=1)
        window = validate_window(window)
        return self._get(
            f"/api/v1/graph/account/{account_id}/neighborhood",
            {"hops": hops, "window": window},
        )

    def transaction_history(
        self, account_id: str, window: str, page: int, page_size: int
    ) -> dict[str, Any]:
        account_id = validate_account_id(account_id)
        window = validate_window(window)
        page = validate_int(page, "page", minimum=1, default=1)
        page_size = validate_int(page_size, "page_size", minimum=1, maximum=100, default=50)
        payload = self._get(
            f"/api/v1/graph/account/{account_id}/transactions",
            {"window": window, "page": page, "page_size": page_size},
        )
        activity = payload.get("activity") or {}
        return {
            "account_id": account_id,
            "window": window,
            "page": page,
            "page_size": page_size,
            "total_transactions": activity.get("total_transactions", payload.get("transaction_count", 0)),
            "total_pages": activity.get("total_pages", 1),
            "settled_amount": payload.get("settled_amount", 0.0),
            "degrees": payload.get("degrees", {}),
            "transactions": activity.get("transactions", []),
        }

    def transaction_details(self, transaction_id: str) -> dict[str, Any]:
        # The graph engine exposes transactions through account history, not a
        # dedicated endpoint. Resolve via the owning account when possible.
        transaction_id = validate_transaction_id(transaction_id)
        raise ToolExecutionError(
            "transaction_details is not exposed by the graph REST API; "
            "run the AI layer in-process (unset MULEGRAPH_AI_GRAPH_API_URL) "
            f"to inspect {transaction_id}"
        )

    # --- pattern detectors ----------------------------------------------
    def detect_fan(self, account_id: str, window: str, direction: str) -> dict[str, Any]:
        account_id = validate_account_id(account_id)
        window = validate_window(window)
        direction = str(direction).upper()
        if direction not in ("IN", "OUT"):
            raise ToolValidationError("direction", "must be 'IN' or 'OUT'")
        patterns = self._get(
            f"/api/v1/graph/account/{account_id}/patterns",
            {"window": window, "profile": "STANDARD", "page_size": 100},
        )
        wanted = "FAN_IN" if direction == "IN" else "FAN_OUT"
        matching = [p for p in patterns.get("patterns", []) if p.get("pattern_type") == wanted]
        if matching:
            result = matching[0]
        else:
            result = {
                "account_id": account_id,
                "direction": direction,
                "detected": False,
                "pattern_type": wanted,
                "unique_accounts": 0,
                "transaction_count": 0,
                "total_amount": 0.0,
                "transactions": [],
                "explanation": f"No {wanted} pattern detected in window {window}.",
            }
        return {"window": window, "risk_assessment": patterns.get("risk_assessment", {}), **result}

    def trace(
        self,
        source: str,
        destination: str,
        max_hops: int,
        window: str,
        min_amount: float | None,
        chronological: bool,
        shortest_only: bool,
    ) -> dict[str, Any]:
        source = validate_account_id(source, "source")
        destination = validate_account_id(destination, "destination")
        max_hops = validate_int(max_hops, "max_hops", minimum=1, maximum=6, default=4)
        window = validate_window(window, default="24h")
        params: dict[str, Any] = {
            "max_hops": max_hops,
            "window": window,
            "chronological": str(bool(chronological)).lower(),
            "shortest_only": str(bool(shortest_only)).lower(),
        }
        if min_amount:
            params["min_amount"] = min_amount
        return self._get(f"/api/v1/graph/trace/{source}/{destination}", params)

    def cycles(
        self, window: str, min_length: int, max_length: int | None, account_id: str | None
    ) -> dict[str, Any]:
        window = validate_window(window, default="24h")
        min_length = validate_int(min_length, "min_length", minimum=2, maximum=8, default=3)
        params: dict[str, Any] = {"window": window, "min_length": min_length}
        if max_length:
            params["max_length"] = validate_int(max_length, "max_length", minimum=3, maximum=8)
        payload = self._get("/api/v1/graph/cycles", params)
        if account_id:
            account_id = validate_account_id(account_id)
            matching = [c for c in payload.get("cycles", []) if account_id in c.get("accounts", [])]
            repeated = [
                r
                for r in payload.get("repeated_activity", [])
                if account_id in r.get("accounts", [])
            ]
            return {
                **payload,
                "account_filter": account_id,
                "total_cycles_in_window": payload.get("cycle_count", 0),
                "cycle_count": len(matching),
                "cycles": matching,
                "repeated_activity": repeated,
            }
        return payload

    def temporal_patterns(self, account_id: str, window: str) -> dict[str, Any]:
        account_id = validate_account_id(account_id)
        window = validate_window(window, default="24h")
        patterns = self._get(
            f"/api/v1/graph/account/{account_id}/patterns",
            {"window": window, "profile": "DEEP", "page_size": 100},
        )
        motif_types = ("TEMPORAL_MOTIF", "RAPID_PASS_THROUGH", "MOTIF")
        motifs = [
            p
            for p in patterns.get("patterns", [])
            if str(p.get("pattern_type", "")).upper() in motif_types
            or "MOTIF" in str(p.get("pattern_type", "")).upper()
        ]
        return {
            "account_id": account_id,
            "time_window": window,
            "motif_count": len(motifs),
            "motifs": motifs,
            "source": "graph engine /patterns endpoint (DEEP profile)",
        }

    def communities(self, account_id: str, window: str, min_size: int) -> dict[str, Any]:
        account_id = validate_account_id(account_id)
        window = validate_window(window, default="24h")
        min_size = validate_int(min_size, "min_size", minimum=2, maximum=50, default=3)
        payload = self._get(
            "/api/v1/graph/communities", {"window": window, "min_size": min_size}
        )
        communities = payload.get("communities", [])
        membership = [c for c in communities if account_id in c.get("members", [])]
        return {
            "account_id": account_id,
            "time_window": window,
            "algorithm": payload.get("algorithm"),
            "community_count": payload.get("community_count", 0),
            "account_communities": membership,
            "top_communities": communities[:5],
        }

    def centrality(self, account_id: str, window: str) -> dict[str, Any]:
        account_id = validate_account_id(account_id)
        window = validate_window(window, default="24h")
        payload = self._get("/api/v1/graph/metrics", {"account_id": account_id, "window": window})
        return {
            "account_id": account_id,
            "time_window": window,
            "account_metrics": payload.get("metrics", {}).get(account_id, {}),
            "is_bridge_node": account_id in (payload.get("bridge_nodes") or []),
            "bridge_nodes": payload.get("bridge_nodes", []),
            "top_pagerank": payload.get("top_pagerank", [])[:10],
            "top_betweenness": payload.get("top_betweenness", [])[:10],
            "parameters": payload.get("parameters", {}),
        }

    def graph_evidence(self, account_id: str, window: str, profile: str) -> dict[str, Any]:
        account_id = validate_account_id(account_id)
        window = validate_window(window, default="24h")
        profile = validate_profile(profile, default="FAST")
        payload = self._post(
            "/api/v1/graph/analyze",
            {
                "account_id": account_id,
                "time_window": window,
                "profile": profile,
                "include_subgraph": False,
            },
        )
        payload.pop("subgraph", None)
        return payload


def create_graph_client(services: dict[str, Any] | None, config: Any) -> GraphClient:
    """Pick HTTP for a remote graph, otherwise use the optional local engine."""
    url = getattr(config, "graph_api_url", None)
    if url:
        logger.info("AI tools will call the graph engine over HTTP: %s", url)
        return HttpGraphClient(url, timeout_s=getattr(config, "graph_api_timeout_s", 15.0))
    if services is None:
        raise ValueError(
            "graph_api_url is required when the AI service runs without an "
            "in-process graph engine"
        )
    return InProcessGraphClient(services)


__all__ = [
    "GraphClient",
    "HttpGraphClient",
    "InProcessGraphClient",
    "create_graph_client",
]
