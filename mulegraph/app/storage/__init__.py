"""Storage abstraction for durable transaction records.

Initial implementation is fully in-memory (with rebuild-from-events support).
PostgreSQL / Redis / Neo4j backends plug in behind the same interface and are
activated only when their dependencies and connection settings are present -
they are never required for the working version.
"""

from __future__ import annotations

import json
import logging
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterable

from ..graph.graph_store import GraphStore
from ..graph.models import TransactionEvent

logger = logging.getLogger("mulegraph.storage")


class TransactionRepository(ABC):
    """Durable record of transaction events (source of truth for rebuilds)."""

    @abstractmethod
    def append(self, event: TransactionEvent) -> None:
        """Persist one event (append-only)."""

    @abstractmethod
    def load_all(self) -> list[TransactionEvent]:
        """Load every persisted event, ordered by timestamp."""

    @abstractmethod
    def count(self) -> int: ...


class InMemoryTransactionRepository(TransactionRepository):
    """Default repository: append-only list (optionally mirrored to disk)."""

    def __init__(self, mirror_path: str | Path | None = None) -> None:
        self._events: list[TransactionEvent] = []
        self._ids: set[str] = set()
        self._lock = threading.Lock()
        self._mirror_path = Path(mirror_path) if mirror_path else None

    def append(self, event: TransactionEvent) -> None:
        with self._lock:
            if event.event_id in self._ids:
                return
            self._ids.add(event.event_id)
            self._events.append(event)
            if self._mirror_path is not None:
                self._mirror(event)

    def load_all(self) -> list[TransactionEvent]:
        with self._lock:
            return sorted(self._events, key=lambda e: (e.timestamp, e.event_id))

    def count(self) -> int:
        with self._lock:
            return len(self._events)

    def _mirror(self, event: TransactionEvent) -> None:
        try:
            self._mirror_path.parent.mkdir(parents=True, exist_ok=True)
            with self._mirror_path.open("a", encoding="utf-8") as fh:
                fh.write(event.model_dump_json() + "\n")
        except OSError:  # pragma: no cover - disk issues must not break ingestion
            logger.warning("failed to mirror event %s to %s", event.event_id, self._mirror_path)


class FileTransactionRepository(InMemoryTransactionRepository):
    """JSONL-backed repository: rebuild graph state from durable events."""

    def __init__(self, path: str | Path) -> None:
        super().__init__(mirror_path=path)
        self._load(path)

    def _load(self, path: str | Path) -> None:
        file_path = Path(path)
        if not file_path.exists():
            return
        for line in file_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = TransactionEvent.model_validate(json.loads(line))
            except Exception as exc:
                logger.warning("skipping corrupt event line: %s", exc)
                continue
            if event.event_id not in self._ids:
                self._ids.add(event.event_id)
                self._events.append(event)


class GraphPersistenceService:
    """Keeps a GraphStore rebuildable from its durable repository."""

    def __init__(self, store: GraphStore, repository: TransactionRepository) -> None:
        self.store = store
        self.repository = repository

    def record(self, event: TransactionEvent) -> None:
        self.repository.append(event)

    def rebuild(self) -> int:
        events: Iterable[TransactionEvent] = self.repository.load_all()
        count = self.store.rebuild_from_events(events)
        logger.info("graph rebuilt from %d durable events", count)
        return count

    def stats(self) -> dict[str, Any]:
        return {"durable_events": self.repository.count(), "graph_version": self.store.version}


def create_repository(settings: dict[str, Any] | None = None) -> TransactionRepository:
    """Factory: JSONL file when ``MULEGRAPH_EVENT_FILE`` is set, else memory."""
    import os

    settings = settings or {}
    path = settings.get("event_file") or os.environ.get("MULEGRAPH_EVENT_FILE")
    if path:
        return FileTransactionRepository(path)
    return InMemoryTransactionRepository()
