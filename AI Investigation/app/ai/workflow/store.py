"""Investigation session store: isolation, snapshots and persistence.

Each investigation is an isolated record keyed by ``investigation_id``;
chat sessions map ``session_id -> investigation_id`` so a conversation always
continues the *same* investigation instead of starting a new one. Snapshots
are deep copies (JSON round-trip) so a running investigation can never be
corrupted by a reader, and long-running investigations can be persisted to
disk when ``MULEGRAPH_AI_STATE_DIR`` is configured.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger("mulegraph.ai.store")


def _snapshot(state: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(state, default=str))


class InvestigationStore:
    def __init__(self, state_dir: str | None = None, max_items: int = 200) -> None:
        self._lock = threading.RLock()
        self._items: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self._sessions: dict[str, str] = {}
        self.state_dir = Path(state_dir) if state_dir else None
        self.max_items = max_items
        if self.state_dir:
            try:
                self.state_dir.mkdir(parents=True, exist_ok=True)
            except OSError:  # pragma: no cover
                logger.warning("state dir %s not writable; memory-only store", state_dir)
                self.state_dir = None

    # ------------------------------------------------------------------ #
    def save(self, state: dict[str, Any]) -> dict[str, Any]:
        snap = _snapshot(state)
        inv_id = str(snap.get("investigation_id", ""))
        if not inv_id:
            return snap
        with self._lock:
            self._items[inv_id] = snap
            self._items.move_to_end(inv_id)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)
            session_id = snap.get("session_id")
            if session_id:
                self._sessions[str(session_id)] = inv_id
        self._persist(snap)
        return snap

    def update(self, inv_id: str, **fields: Any) -> None:
        with self._lock:
            current = self._items.get(inv_id)
            if current is None:
                return
            current.update(fields)
        self._persist(current)

    def get(self, inv_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._items.get(inv_id)
            return _snapshot(state) if state else None

    def by_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            inv_id = self._sessions.get(session_id)
        return self.get(inv_id) if inv_id else None

    def link_session(self, session_id: str, inv_id: str) -> None:
        with self._lock:
            self._sessions[str(session_id)] = inv_id

    def exists(self, inv_id: str) -> bool:
        with self._lock:
            return inv_id in self._items

    def ids(self) -> list[str]:
        with self._lock:
            return list(self._items)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        with self._lock:
            items = [_snapshot(s) for s in self._items.values()]
        return iter(items)

    # ------------------------------------------------------------------ #
    def _persist(self, snap: dict[str, Any]) -> None:
        if not self.state_dir:
            return
        inv_id = str(snap.get("investigation_id", ""))
        if not inv_id.replace("-", "").replace("_", "").isalnum():
            return
        path = self.state_dir / f"{inv_id}.json"
        try:
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(snap, default=str, indent=1), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:  # pragma: no cover
            logger.debug("persist failed for %s", inv_id, exc_info=True)

    def load_all(self) -> int:
        """Load persisted investigations (used on service start)."""
        if not self.state_dir:
            return 0
        loaded = 0
        for path in sorted(self.state_dir.glob("INV-*.json")):
            try:
                snap = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            inv_id = str(snap.get("investigation_id", ""))
            if not inv_id:
                continue
            with self._lock:
                self._items[inv_id] = snap
                session_id = snap.get("session_id")
                if session_id:
                    self._sessions[str(session_id)] = inv_id
            loaded += 1
        return loaded


__all__ = ["InvestigationStore"]
