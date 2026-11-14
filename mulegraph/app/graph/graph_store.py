"""Graph storage: a directed temporal multigraph backed by NetworkX.

* every account is a node
* every transaction is its own directed edge (``key = transaction_id``)
* multiple transactions between the same accounts are all preserved
* edge attributes keep timestamp, amount, status and status history
* thread-safe incremental updates - the graph is never rebuilt wholesale
"""

from __future__ import annotations

import threading
from typing import Any, Iterable

import networkx as nx

from ..config import GraphConfig
from .adjacency_index import AdjacencyIndex, Window
from .models import (
    ApplyResult,
    LimitExceededError,
    TransactionEvent,
    TransactionRecord,
    TransactionStatus,
    is_settled,
)


class GraphStore:
    """Owns the multigraph, adjacency/time indexes and transaction records."""

    def __init__(self, config: GraphConfig | None = None) -> None:
        self.config = config or GraphConfig()
        self.graph: nx.MultiDiGraph = nx.MultiDiGraph()
        self.index = AdjacencyIndex(max_degree=self.config.max_degree)
        self.transactions: dict[str, TransactionRecord] = {}
        self.processed_events: set[str] = set()
        self.version: int = 0
        self._lock = threading.RLock()
        self._rejected_events: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    # ingestion
    # ------------------------------------------------------------------ #
    def add_event(self, event: TransactionEvent) -> ApplyResult:
        """Incrementally apply one transaction event (thread-safe)."""
        with self._lock:
            if event.event_id in self.processed_events:
                return ApplyResult(
                    transaction_id=event.transaction_id,
                    event_id=event.event_id,
                    accepted=False,
                    action="duplicate",
                    graph_version=self.version,
                    detail="event already processed",
                )

            existing = self.transactions.get(event.transaction_id)
            if existing is None:
                return self._create_transaction(event)
            return self._update_transaction(event, existing)

    def _create_transaction(self, event: TransactionEvent) -> ApplyResult:
        if self.index.node_count >= self.config.max_nodes and not (
            event.source_account in self.graph and event.destination_account in self.graph
        ):
            raise LimitExceededError(
                f"max_nodes limit reached ({self.config.max_nodes}); transaction {event.transaction_id} not ingested"
            )
        if self.index.edge_count >= self.config.max_edges:
            raise LimitExceededError(
                f"max_edges limit reached ({self.config.max_edges}); transaction {event.transaction_id} not ingested"
            )

        src, dst = event.source_account, event.destination_account
        self._touch_node(src, event.timestamp)
        self._touch_node(dst, event.timestamp)

        added = self.index.add_edge(src, dst, event.transaction_id, event.timestamp)
        if not added:
            self._rejected_events.append(
                {
                    "transaction_id": event.transaction_id,
                    "reason": "max_degree_exceeded",
                    "account": src if len(self._out_degree(src)) else dst,
                }
            )
            return ApplyResult(
                transaction_id=event.transaction_id,
                event_id=event.event_id,
                accepted=False,
                action="rejected",
                graph_version=self.version,
                detail="degree limit exceeded",
            )

        # MultiDiGraph: one edge per transaction, keyed by transaction id.
        self.graph.add_edge(
            src,
            dst,
            key=event.transaction_id,
            transaction_id=event.transaction_id,
            amount=event.amount,
            currency=event.currency,
            timestamp=event.timestamp,
            status=event.status.value,
            settled=is_settled(event.status),
            event_type=event.event_type,
            updated_at=event.timestamp,
            status_history=[],
        )

        record = TransactionRecord(
            transaction_id=event.transaction_id,
            source_account=src,
            destination_account=dst,
            amount=event.amount,
            currency=event.currency,
            created_at=event.timestamp,
            status=event.status,
            updated_at=event.timestamp,
            original_event=event,
            history=[(event.timestamp, event.status, event.event_id)],
        )
        self.transactions[event.transaction_id] = record
        self.processed_events.add(event.event_id)
        self.version += 1
        return ApplyResult(
            transaction_id=event.transaction_id,
            event_id=event.event_id,
            accepted=True,
            action="created",
            graph_version=self.version,
        )

    def _update_transaction(self, event: TransactionEvent, record: TransactionRecord) -> ApplyResult:
        """Apply a status update while preserving the original event."""
        if event.event_type.upper() == "STATUS_UPDATE" or event.status != record.status:
            previous = record.status
            record.status = event.status
            record.updated_at = event.timestamp
            record.history.append((event.timestamp, event.status, event.event_id))

            attrs = self.graph.get_edge_data(
                record.source_account, record.destination_account, event.transaction_id
            )
            if attrs is not None:
                attrs["status"] = event.status.value
                attrs["settled"] = is_settled(event.status)
                attrs["updated_at"] = event.timestamp
                attrs["status_history"] = [
                    {"timestamp": ts, "status": st.value, "event_id": eid}
                    for ts, st, eid in record.history
                ]
                # reversal bookkeeping: keep the edge (evidence!) but flag it
                if event.status == TransactionStatus.REVERSED:
                    attrs["reversed_at"] = event.timestamp
                    attrs["original_status"] = previous.value

            self.processed_events.add(event.event_id)
            self.version += 1
            return ApplyResult(
                transaction_id=record.transaction_id,
                event_id=event.event_id,
                accepted=True,
                action="status_update",
                graph_version=self.version,
                detail=f"{previous.value} -> {event.status.value}",
            )

        self.processed_events.add(event.event_id)
        return ApplyResult(
            transaction_id=record.transaction_id,
            event_id=event.event_id,
            accepted=False,
            action="duplicate",
            graph_version=self.version,
            detail="transaction already in this state",
        )

    def _touch_node(self, account: str, ts: float) -> None:
        if account not in self.graph:
            self.graph.add_node(
                account, account_id=account, first_seen=ts, last_seen=ts, events=1
            )
            return
        data = self.graph.nodes[account]
        data["first_seen"] = min(data["first_seen"], ts)
        data["last_seen"] = max(data["last_seen"], ts)
        data["events"] += 1

    def _out_degree(self, account: str) -> dict[str, list[str]]:
        return self.graph._adj.get(account, {})  # noqa: SLF001 - internal fast path

    # ------------------------------------------------------------------ #
    # queries
    # ------------------------------------------------------------------ #
    def has_account(self, account_id: str) -> bool:
        return account_id in self.graph

    def get_transaction(self, transaction_id: str) -> TransactionRecord | None:
        return self.transactions.get(transaction_id)

    def transactions_for_account(
        self, account_id: str, window: Window | None = None, settled_only: bool = False
    ) -> list[TransactionRecord]:
        out = [
            self.transactions[tx]
            for _, _, tx in self.index.out_neighbors(account_id, window)
            if tx in self.transactions
        ]
        inn = [
            self.transactions[tx]
            for _, _, tx in self.index.in_neighbors(account_id, window)
            if tx in self.transactions
        ]
        seen: set[str] = set()
        merged: list[TransactionRecord] = []
        for rec in out + inn:
            if rec.transaction_id in seen:
                continue
            seen.add(rec.transaction_id)
            if settled_only and not rec.is_settled:
                continue
            merged.append(rec)
        merged.sort(key=lambda r: r.created_at)
        return merged

    def windowed_graph(self, window: Window, settled_only: bool = True) -> nx.MultiDiGraph:
        """Build a lightweight view of edges inside a time window.

        Only the window's edges are copied (bounded); this is used for
        community/centrality analysis which needs a graph structure, not for
        neighbourhood lookups (those go through the index).
        """
        sub = nx.MultiDiGraph()
        for ts, src, dst, tx_id in self.index.edges_in_window(window):
            record = self.transactions.get(tx_id)
            if record is None:
                continue
            if settled_only and not record.is_settled:
                continue
            if src not in sub:
                sub.add_node(src, **self.graph.nodes[src])
            if dst not in sub:
                sub.add_node(dst, **self.graph.nodes[dst])
            data = self.graph.get_edge_data(src, dst, tx_id)
            if data is not None:
                sub.add_edge(src, dst, key=tx_id, **data)
        return sub

    def stats(self) -> dict[str, Any]:
        with self._lock:
            status_counts: dict[str, int] = {}
            total_volume = 0.0
            for rec in self.transactions.values():
                status_counts[rec.status.value] = status_counts.get(rec.status.value, 0) + 1
                if rec.is_settled:
                    total_volume += rec.amount
            return {
                "graph_version": self.version,
                "nodes": self.graph.number_of_nodes(),
                "edges": self.graph.number_of_edges(),
                "transactions": len(self.transactions),
                "unique_events": len(self.processed_events),
                "rejected_events": len(self._rejected_events),
                "status_counts": status_counts,
                "settled_volume": round(total_volume, 2),
                "index": self.index.stats(),
            }

    def degrees(self, account_id: str, window: Window | None = None) -> dict[str, int]:
        return {
            "in_degree": self.index.degree_in(account_id, window),
            "out_degree": self.index.degree_out(account_id, window),
            "unique_in": self.index.unique_in(account_id, window),
            "unique_out": self.index.unique_out(account_id, window),
        }

    def neighborhood(
        self, account_id: str, hops: int = 1, window: Window | None = None, limit: int = 500
    ) -> tuple[set[str], list[tuple[str, str, str, float]]]:
        """Bounded BFS neighbourhood. Returns (nodes, edges as src/dst/tx/ts)."""
        if hops < 1:
            raise ValueError("hops must be >= 1")
        nodes: set[str] = {account_id}
        frontier = {account_id}
        edges: list[tuple[str, str, str, float]] = []
        seen_edges: set[str] = set()
        limit = min(limit, self.config.max_traversal_nodes)

        for _ in range(hops):
            if len(nodes) >= limit:
                break
            nxt: set[str] = set()
            for node in frontier:
                if len(nodes) >= limit:
                    break
                for ts, other, tx in self.index.out_neighbors(node, window):
                    if tx not in seen_edges:
                        seen_edges.add(tx)
                        edges.append((node, other, tx, ts))
                    if other not in nodes and len(nodes) < limit:
                        nodes.add(other)
                        nxt.add(other)
                for ts, other, tx in self.index.in_neighbors(node, window):
                    if tx not in seen_edges:
                        seen_edges.add(tx)
                        edges.append((other, node, tx, ts))
                    if other not in nodes and len(nodes) < limit:
                        nodes.add(other)
                        nxt.add(other)
            if not nxt or len(nodes) >= limit:
                break
            frontier = nxt
        return nodes, edges

    def rebuild_from_events(self, events: Iterable[TransactionEvent]) -> int:
        """Rebuild the whole graph from durable events (recovery path)."""
        with self._lock:
            self.graph.clear()
            self.index = AdjacencyIndex(max_degree=self.config.max_degree)
            self.transactions.clear()
            self.processed_events.clear()
            self.version = 0
            count = 0
            for event in sorted(events, key=lambda e: (e.timestamp, e.event_id)):
                result = self.add_event(event)
                if result.accepted:
                    count += 1
            return count
