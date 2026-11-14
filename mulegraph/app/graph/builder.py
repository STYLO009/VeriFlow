"""Graph builder: incremental, duplicate-safe ingestion of transaction events.

``GraphBuilder`` is the single write path into the :class:`GraphStore`. It
validates events, deduplicates them, applies status transitions and keeps the
temporal indexes consistent - without ever rebuilding the graph.
"""

from __future__ import annotations

import logging
from typing import Any

from .graph_store import GraphStore
from .models import ApplyResult, EventValidationError, TransactionEvent

logger = logging.getLogger("mulegraph.builder")


class GraphBuilder:
    """Incremental graph construction with dedupe and validation."""

    def __init__(self, store: GraphStore) -> None:
        self.store = store

    def build(self, event: TransactionEvent | dict[str, Any]) -> ApplyResult:
        """Validate and ingest one transaction event."""
        if isinstance(event, dict):
            try:
                event = TransactionEvent.model_validate(event)
            except Exception as exc:  # pydantic ValidationError
                raise EventValidationError(f"invalid transaction event: {exc}") from exc

        if not isinstance(event, TransactionEvent):
            raise EventValidationError(f"expected TransactionEvent, got {type(event).__name__}")

        if event.source_account == event.destination_account:
            logger.debug(
                "self-transfer accepted as evidence: tx=%s account=%s",
                event.transaction_id,
                event.source_account,
            )

        result = self.store.add_event(event)
        if result.action == "duplicate":
            logger.debug("duplicate event skipped: %s", event.event_id)
        elif result.action == "status_update":
            logger.info("status update: tx=%s %s", event.transaction_id, result.detail)
        return result

    def build_many(self, events: list[TransactionEvent | dict[str, Any]]) -> list[ApplyResult]:
        return [self.build(e) for e in events]
