"""Audit logging for the AI layer.

Records what the AI did (tool calls, model calls, provider switches,
validation problems, report generation) with key-safe, minimised payloads.
Full tool payloads are never written to the audit log - only identifiers,
sizes, durations and outcomes - so sensitive transaction detail is not
duplicated into log files.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("mulegraph.ai.audit")

_REDACT_KEYS = ("api_key", "authorization", "token", "secret", "password")


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = str(key).lower()
        if any(marker in lowered for marker in _REDACT_KEYS):
            safe[key] = "[redacted]"
        elif isinstance(value, dict):
            safe[key] = _redact(value)
        else:
            safe[key] = value
    return safe


@dataclass
class AuditEvent:
    at: float
    kind: str
    investigation_id: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "kind": self.kind,
            "investigation_id": self.investigation_id,
            "payload": self.payload,
        }


class AuditLog:
    def __init__(self, path: str | None = None, memory_limit: int = 500) -> None:
        self.path = path
        self._memory: deque[AuditEvent] = deque(maxlen=memory_limit)
        self._lock = threading.Lock()
        self.count = 0
        if path:
            try:
                directory = os.path.dirname(os.path.abspath(path))
                os.makedirs(directory, exist_ok=True)
            except OSError:  # pragma: no cover - filesystem quirks
                logger.warning("audit path %s not writable; memory-only audit", path)
                self.path = None

    # ------------------------------------------------------------------ #
    def record(
        self, kind: str, investigation_id: str, **payload: Any
    ) -> AuditEvent:
        event = AuditEvent(
            at=time.time(),
            kind=kind,
            investigation_id=investigation_id or "-",
            payload=_redact(payload),
        )
        with self._lock:
            self.count += 1
            self._memory.append(event)
            if self.path:
                try:
                    with open(self.path, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(event.to_dict(), default=str) + "\n")
                except OSError:  # pragma: no cover - never break a request
                    logger.warning("failed to append audit event to %s", self.path)
        return event

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            events = list(self._memory)[-limit:]
        return [e.to_dict() for e in events]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "count": self.count,
                "memory_events": len(self._memory),
                "file": self.path,
            }


__all__ = ["AuditLog", "AuditEvent"]
