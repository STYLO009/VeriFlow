"""Temporal graph helpers: windows, windowed views and time filtering."""

from __future__ import annotations

import time
from typing import Any

from .adjacency_index import Window
from .graph_store import GraphStore

__all__ = ["Window", "TemporalGraph"]


class TemporalGraph:
    """Thin facade that exposes time-window operations over a GraphStore."""

    def __init__(self, store: GraphStore) -> None:
        self.store = store

    def window(self, name: str, reference: float | None = None) -> Window:
        """Resolve a preset window (``5s`` .. ``24h``) relative to a timestamp."""
        return Window.preset(name, reference)

    def window_at(self, name: str, anchor: float) -> Window:
        """Window ending at ``anchor`` (used to analyse a historical event)."""
        return Window.preset(name, reference=anchor)

    def now_window(self, name: str) -> Window:
        return Window.preset(name, reference=time.time())

    def edges(self, window: Window) -> list[tuple[float, str, str, str]]:
        """All individual transaction edges inside the window."""
        return self.store.index.edges_in_window(window)

    def account_activity(
        self, account_id: str, window: Window
    ) -> dict[str, Any]:
        """Aggregated in/out activity for an account inside a window.

        Counts only *settled* (COMPLETED) transactions as money movement;
        held / rejected / reversed / pending are reported separately.
        """
        incoming: list[tuple[float, str, str]] = []
        outgoing: list[tuple[float, str, str]] = []
        non_settled = 0

        def _partition(entries: list[tuple[float, str, str]], target: list[tuple[float, str, str]]) -> None:
            nonlocal non_settled
            for entry in entries:
                record = self.store.transactions.get(entry[2])
                if record is None:
                    continue
                if record.is_settled:
                    target.append(entry)
                else:
                    non_settled += 1

        _partition(self.store.index.in_neighbors(account_id, window), incoming)
        _partition(self.store.index.out_neighbors(account_id, window), outgoing)

        records = self.store.transactions_for_account(account_id, window)
        settled = [r for r in records if r.is_settled]
        return {
            "account_id": account_id,
            "window": window.to_dict(),
            "incoming_transactions": len(incoming),
            "outgoing_transactions": len(outgoing),
            "unique_incoming_accounts": len({other for _, other, _ in incoming}),
            "unique_outgoing_accounts": len({other for _, other, _ in outgoing}),
            "incoming_amount": round(sum(r.amount for r in settled if r.source_account != account_id), 2),
            "outgoing_amount": round(sum(r.amount for r in settled if r.source_account == account_id), 2),
            "settled_transactions": len(settled),
            "non_settled_transactions": len(records) - len(settled),
        }

    def slice(self, window: Window, settled_only: bool = True):
        """Return a windowed MultiDiGraph view (bounded copy)."""
        return self.store.windowed_graph(window, settled_only=settled_only)

    def historical(self, anchor: float, name: str = "5m") -> dict[str, Any]:
        """Historical query: graph stats as they looked around ``anchor``."""
        window = self.window_at(name, anchor)
        edges = self.edges(window)
        nodes: set[str] = set()
        for _, src, dst, _ in edges:
            nodes.add(src)
            nodes.add(dst)
        return {
            "anchor": anchor,
            "window": window.to_dict(),
            "nodes": len(nodes),
            "edges": len(edges),
        }
