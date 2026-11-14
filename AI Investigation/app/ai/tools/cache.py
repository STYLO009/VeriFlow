"""Graph-version aware cache for investigation tool results.

A cached result is only served when the graph has not changed since it was
produced (``graph_version`` match) and it is younger than the TTL, so a
repeated tool call during one investigation does not re-run expensive graph
algorithms but can never return stale evidence after new transactions land.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class CacheEntry:
    data: Any
    graph_version: int
    created_at: float
    hits: int = 0


class ToolResultCache:
    def __init__(
        self,
        enabled: bool = True,
        ttl_s: float = 30.0,
        max_entries: int = 256,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.enabled = enabled
        self.ttl_s = ttl_s
        self.max_entries = max_entries
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, CacheEntry] = OrderedDict()
        self.hits = 0
        self.misses = 0
        self.invalidations = 0

    # ------------------------------------------------------------------ #
    @staticmethod
    def make_key(tool: str, arguments: dict[str, Any]) -> str:
        payload = json.dumps(
            {"tool": tool, "args": arguments}, sort_keys=True, default=str
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, tool: str, arguments: dict[str, Any], graph_version: int) -> Any | None:
        if not self.enabled:
            return None
        key = self.make_key(tool, arguments)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.misses += 1
                return None
            expired = (self._clock() - entry.created_at) > self.ttl_s
            stale = entry.graph_version != graph_version
            if expired or stale:
                self._entries.pop(key, None)
                self.misses += 1
                if stale:
                    self.invalidations += 1
                return None
            entry.hits += 1
            self.hits += 1
            self._entries.move_to_end(key)
            return entry.data

    def put(self, tool: str, arguments: dict[str, Any], graph_version: int, data: Any) -> None:
        if not self.enabled:
            return
        key = self.make_key(tool, arguments)
        with self._lock:
            self._entries[key] = CacheEntry(
                data=data, graph_version=graph_version, created_at=self._clock()
            )
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "entries": len(self._entries),
                "hits": self.hits,
                "misses": self.misses,
                "invalidations": self.invalidations,
                "ttl_s": self.ttl_s,
            }


__all__ = ["ToolResultCache"]
