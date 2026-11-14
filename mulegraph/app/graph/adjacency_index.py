"""Adjacency + time indexes for fast neighbourhood queries.

Design goals:

* O(1) adjacency lookups (source -> destinations, destination -> sources)
* O(log n) time-window range queries via sorted timestamp arrays + ``bisect``
* incremental updates only - the full graph is never rebuilt
* degree caps so a single hub account cannot blow up memory

Every transaction edge is preserved individually: the index stores transaction
ids, never collapsed aggregate edges.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Iterable

from ..config import WINDOW_PRESETS

# (timestamp, other_account, transaction_id)
TimeEntry = tuple[float, str, str]


@dataclass(frozen=True)
class Window:
    """Half-open time interval ``[start, end)`` in epoch seconds."""

    start: float
    end: float

    def __contains__(self, ts: float) -> bool:
        return self.start <= ts < self.end

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @classmethod
    def last(cls, seconds: float, reference: float | None = None) -> "Window":
        ref = reference if reference is not None else _now()
        return cls(start=ref - seconds, end=ref + 1e-6)

    @classmethod
    def preset(cls, name: str, reference: float | None = None) -> "Window":
        key = name.strip().lower()
        if key not in WINDOW_PRESETS:
            raise ValueError(
                f"Unknown time window {name!r}. Valid options: {', '.join(WINDOW_PRESETS)}"
            )
        return cls.last(WINDOW_PRESETS[key], reference)

    @classmethod
    def between(cls, start: float, end: float) -> "Window":
        if end < start:
            raise ValueError("window end must not be before start")
        return cls(start=start, end=end)

    def to_dict(self) -> dict[str, float]:
        return {"start": self.start, "end": self.end, "duration_seconds": self.duration}


def _now() -> float:
    import time

    return time.time()


def _range(sorted_entries: list[TimeEntry], window: Window | None) -> list[TimeEntry]:
    """Return entries whose timestamp falls inside ``window`` (O(log n))."""
    if window is None:
        return list(sorted_entries)
    lo = bisect.bisect_left(sorted_entries, window.start, key=lambda e: e[0])
    hi = bisect.bisect_left(sorted_entries, window.end, key=lambda e: e[0])
    return sorted_entries[lo:hi]


class AdjacencyIndex:
    """In-memory adjacency + time index over transaction edges."""

    __slots__ = (
        "_out",
        "_in",
        "_out_time",
        "_in_time",
        "_all_time",
        "_max_degree",
        "_edge_count",
    )

    def __init__(self, max_degree: int = 5000) -> None:
        # account -> account -> [transaction_id, ...]  (multiedge preserved)
        self._out: dict[str, dict[str, list[str]]] = {}
        self._in: dict[str, dict[str, list[str]]] = {}
        # account -> sorted [(ts, other, tx_id)] for windowed range scans
        self._out_time: dict[str, list[TimeEntry]] = {}
        self._in_time: dict[str, list[TimeEntry]] = {}
        # globally sorted time index for window-scoped edge extraction
        self._all_time: list[tuple[float, str, str, str]] = []  # (ts, src, dst, tx_id)
        self._max_degree = max_degree
        self._edge_count = 0

    # ------------------------------------------------------------------ #
    # mutation
    # ------------------------------------------------------------------ #
    def add_edge(self, src: str, dst: str, tx_id: str, ts: float, degree_guard: bool = True) -> bool:
        """Register one directed transaction edge. Returns False if capped."""
        if degree_guard:
            out_degree = len(self._out.get(src, {}))
            in_degree = len(self._in.get(dst, {}))
            if out_degree >= self._max_degree and dst not in self._out.get(src, {}):
                return False
            if in_degree >= self._max_degree and src not in self._in.get(dst, {}):
                return False

        self._out.setdefault(src, {}).setdefault(dst, []).append(tx_id)
        self._in.setdefault(dst, {}).setdefault(src, []).append(tx_id)

        out_list = self._out_time.setdefault(src, [])
        bisect.insort(out_list, (ts, dst, tx_id))
        in_list = self._in_time.setdefault(dst, [])
        bisect.insort(in_list, (ts, src, tx_id))
        bisect.insort(self._all_time, (ts, src, dst, tx_id))

        self._edge_count += 1
        return True

    def remove_edge(self, src: str, dst: str, tx_id: str, ts: float) -> bool:
        """Remove one edge (used for reversal housekeeping; rare path)."""
        dst_map = self._out.get(src)
        if not dst_map or tx_id not in dst_map.get(dst, []):
            return False
        dst_map[dst].remove(tx_id)
        if not dst_map[dst]:
            del dst_map[dst]
        src_map = self._in.get(dst)
        if src_map:
            if tx_id in src_map.get(src, []):
                src_map[src].remove(tx_id)
                if not src_map[src]:
                    del src_map[src]
        self._remove_from(self._out_time.get(src, []), (ts, dst, tx_id))
        self._remove_from(self._in_time.get(dst, []), (ts, src, tx_id))
        for idx, entry in enumerate(self._all_time):
            if entry[3] == tx_id and entry[1] == src and entry[2] == dst:
                del self._all_time[idx]
                break
        self._edge_count -= 1
        return True

    @staticmethod
    def _remove_from(lst: list[TimeEntry], entry: TimeEntry) -> None:
        idx = bisect.bisect_left(lst, entry)
        if idx < len(lst) and lst[idx] == entry:
            del lst[idx]

    # ------------------------------------------------------------------ #
    # adjacency queries
    # ------------------------------------------------------------------ #
    def out_neighbors(self, src: str, window: Window | None = None) -> list[TimeEntry]:
        return _range(self._out_time.get(src, []), window)

    def in_neighbors(self, dst: str, window: Window | None = None) -> list[TimeEntry]:
        return _range(self._in_time.get(dst, []), window)

    def out_accounts(self, src: str, window: Window | None = None) -> set[str]:
        return {other for _, other, _ in self.out_neighbors(src, window)}

    def in_accounts(self, dst: str, window: Window | None = None) -> set[str]:
        return {other for _, other, _ in self.in_neighbors(dst, window)}

    def edges_between(self, src: str, dst: str, window: Window | None = None) -> list[TimeEntry]:
        """All individual transactions src -> dst (never collapsed)."""
        return [e for e in self.out_neighbors(src, window) if e[1] == dst]

    def transaction_ids(self, src: str, dst: str, window: Window | None = None) -> list[str]:
        return [tx for _, _, tx in self.edges_between(src, dst, window)]

    def edges_in_window(self, window: Window) -> list[tuple[float, str, str, str]]:
        """All edges (ts, src, dst, tx_id) inside the window."""
        return _range(self._all_time, window)  # type: ignore[arg-type]

    def degree_out(self, src: str, window: Window | None = None) -> int:
        return len(self.out_neighbors(src, window))

    def degree_in(self, dst: str, window: Window | None = None) -> int:
        return len(self.in_neighbors(dst, window))

    def unique_out(self, src: str, window: Window | None = None) -> int:
        return len({other for _, other, _ in self.out_neighbors(src, window)})

    def unique_in(self, dst: str, window: Window | None = None) -> int:
        return len({other for _, other, _ in self.in_neighbors(dst, window)})

    def accounts(self) -> set[str]:
        return set(self._out) | set(self._in)

    @property
    def edge_count(self) -> int:
        return self._edge_count

    @property
    def node_count(self) -> int:
        return len(self.accounts())

    def top_accounts_by_degree(self, limit: int | None = None) -> list[tuple[str, int]]:
        """Accounts sorted by total degree (descending) - candidate seeds."""
        degrees: dict[str, int] = {}
        for acc, dsts in self._out.items():
            degrees[acc] = degrees.get(acc, 0) + sum(len(v) for v in dsts.values())
        for acc, srcs in self._in.items():
            degrees[acc] = degrees.get(acc, 0) + sum(len(v) for v in srcs.values())
        ordered = sorted(degrees.items(), key=lambda kv: kv[1], reverse=True)
        return ordered[:limit] if limit else ordered

    def stats(self) -> dict[str, int]:
        return {
            "nodes": self.node_count,
            "edges": self._edge_count,
            "indexed_out_nodes": len(self._out_time),
            "indexed_in_nodes": len(self._in_time),
        }

    def iter_all_edges(self) -> Iterable[tuple[float, str, str, str]]:
        return list(self._all_time)
