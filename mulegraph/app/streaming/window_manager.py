"""Sliding-window counters for streaming-time analytics.

Windows: 5s, 30s, 5m, 1h, 24h - each backed by fixed-size bucket rings so
updates are O(1) and expired buckets are dropped automatically. This gives the
FAST analysis profile cheap time-window counts without scanning the graph.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..config import WINDOW_PRESETS

# buckets per window (window duration / bucket size)
_BUCKET_SPEC: dict[str, tuple[float, int]] = {
    "5s": (1.0, 5),        # 1s buckets
    "30s": (5.0, 6),       # 5s buckets
    "5m": (30.0, 10),      # 30s buckets
    "1h": (300.0, 12),     # 5min buckets
    "24h": (900.0, 96),    # 15min buckets
}


@dataclass
class _BucketRing:
    bucket_seconds: float
    count: int
    buckets: list[list[float]] = field(default_factory=list)  # [timestamp_sum, amount_sum, n]
    starts: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.buckets = [[0.0, 0.0, 0.0] for _ in range(self.count)]
        self.starts = [0.0] * self.count

    def add(self, ts: float, amount: float) -> None:
        idx = int(ts // self.bucket_seconds) % self.count
        # guard against stale reuse of the same ring slot
        bucket_start = int(ts // self.bucket_seconds) * self.bucket_seconds
        if self.starts[idx] != bucket_start:
            self.buckets[idx] = [0.0, 0.0, 0.0]
            self.starts[idx] = bucket_start
        b = self.buckets[idx]
        b[0] += ts
        b[1] += amount
        b[2] += 1.0

    def sum(self, window_start: float, window_end: float) -> tuple[int, float]:
        total = 0
        amount = 0.0
        for start, b in zip(self.starts, self.buckets):
            if b[2] == 0.0:
                continue
            if window_start <= start < window_end:
                total += int(b[2])
                amount += b[1]
        return total, round(amount, 2)


class WindowManager:
    """Per-account rolling counters for all preset windows (thread-safe)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # account -> window -> ring
        self._in: dict[str, dict[str, _BucketRing]] = {}
        self._out: dict[str, dict[str, _BucketRing]] = {}
        self._events = 0
        self._late_events = 0
        self._duplicate_events = 0

    # ------------------------------------------------------------------ #
    def record(
        self,
        account: str,
        direction: str,
        ts: float,
        amount: float,
        now: float | None = None,
    ) -> dict[str, int]:
        """Record one settled transaction direction; returns per-window counts."""
        now = now if now is not None else time.time()
        table = self._in if direction == "IN" else self._out
        with self._lock:
            rings = table.setdefault(account, {})
            for name, (bucket_s, buckets_n) in _BUCKET_SPEC.items():
                ring = rings.get(name)
                if ring is None:
                    ring = _BucketRing(bucket_seconds=bucket_s, count=buckets_n)
                    rings[name] = ring
                ring.add(ts, amount)
            if ts < now - WINDOW_PRESETS["24h"]:
                self._late_events += 1
            self._events += 1
            return self._counts_locked(account, now)

    def mark_duplicate(self) -> None:
        with self._lock:
            self._duplicate_events += 1

    # ------------------------------------------------------------------ #
    def counts(self, account: str, now: float | None = None) -> dict[str, Any]:
        now = now if now is not None else time.time()
        with self._lock:
            return {
                "in": self._counts_locked(account, now, table=self._in),
                "out": self._counts_locked(account, now, table=self._out),
            }

    def _counts_locked(
        self,
        account: str,
        now: float,
        table: dict[str, dict[str, _BucketRing]] | None = None,
    ) -> dict[str, int]:
        table = table if table is not None else self._in
        rings = table.get(account, {})
        out: dict[str, int] = {}
        for name, (bucket_s, _) in _BUCKET_SPEC.items():
            window_len = WINDOW_PRESETS[name]
            ring = rings.get(name)
            if ring is None:
                out[name] = 0
                continue
            count, _amount = ring.sum(now - window_len, now + bucket_s)
            out[name] = count
        return out

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "tracked_accounts": len(set(self._in) | set(self._out)),
                "events": self._events,
                "late_events": self._late_events,
                "duplicate_events": self._duplicate_events,
            }
