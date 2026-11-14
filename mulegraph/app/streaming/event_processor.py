"""Streaming-compatible graph event processor.

Pipeline for every transaction event:

1. validate the event (pydantic)
2. prevent duplicate processing (event id + transaction state)
3. update graph state (incremental - never a rebuild)
4. update temporal indexes / rolling window counters
5. run FAST graph analysis
6. build structured graph evidence
7. publish the result to a pluggable sink (Kafka/Redis/webhook/in-memory)

The processor is deliberately independent of any specific broker: it works with
a local synthetic simulator just as well as with Kafka/Redpanda.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from ..algorithms.fan_detection import detect_fan_in, detect_fan_out
from ..graph.builder import GraphBuilder
from ..graph.graph_store import GraphStore
from ..graph.models import ApplyResult, TransactionEvent
from ..intelligence.explainability import build_evidence_bundle, evidence_digest, graph_fact
from ..intelligence.risk_engine import assess
from .window_manager import WindowManager

logger = logging.getLogger("mulegraph.processor")

EvidenceSink = Callable[[dict[str, Any]], None]


class EventSource(Protocol):
    """Pluggable source of transaction events."""

    def poll(self, batch_size: int = 100) -> list[TransactionEvent]: ...


@dataclass
class ProcessingResult:
    event_id: str
    transaction_id: str
    accepted: bool
    action: str
    analysis: dict[str, Any] = field(default_factory=dict)
    published: bool = False
    elapsed_ms: float = 0.0
    graph_version: int = 0
    detail: str = ""


class GraphEventProcessor:
    """Validates, dedupes, ingests, analyses and publishes transaction events."""

    def __init__(
        self,
        builder: GraphBuilder,
        store: GraphStore,
        window_manager: WindowManager | None = None,
        sink: EvidenceSink | None = None,
        profile: str = "FAST",
        emit_non_settled: bool = False,
    ) -> None:
        self.builder = builder
        self.store = store
        self.windows = window_manager or WindowManager()
        self.sink = sink
        self.profile = profile
        self.emit_non_settled = emit_non_settled
        self.processed = 0
        self.published = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    def process(self, event: TransactionEvent | dict[str, Any]) -> ProcessingResult:
        """Full pipeline for one event. Thread-safe."""
        started = time.perf_counter()
        if isinstance(event, dict):
            event = TransactionEvent.model_validate(event)

        result: ApplyResult = self.builder.build(event)

        if result.action == "duplicate":
            self.windows.mark_duplicate()
            return ProcessingResult(
                event_id=event.event_id,
                transaction_id=event.transaction_id,
                accepted=False,
                action="duplicate",
                elapsed_ms=_ms(started),
                graph_version=result.graph_version,
                detail=result.detail,
            )

        if not result.accepted:
            return ProcessingResult(
                event_id=event.event_id,
                transaction_id=event.transaction_id,
                accepted=False,
                action=result.action,
                analysis={"detail": result.detail},
                elapsed_ms=_ms(started),
                graph_version=result.graph_version,
                detail=result.detail,
            )

        # --- temporal indexes -------------------------------------------
        direction = "IN" if event.event_type.upper() != "STATUS_UPDATE" else None
        record = self.store.get_transaction(event.transaction_id)
        if record is not None and record.is_settled and event.source_account != event.destination_account:
            self.windows.record(record.source_account, "OUT", record.created_at, record.amount)
            self.windows.record(record.destination_account, "IN", record.created_at, record.amount)

        # --- fast analysis + evidence ------------------------------------
        analysis = self._fast_analysis(event) if record is not None else {}
        published = False
        if self.sink is not None and (
            self.emit_non_settled or record is None or record.is_settled
        ):
            payload = {
                "event_id": event.event_id,
                "transaction_id": event.transaction_id,
                "graph_version": result.graph_version,
                "action": result.action,
                "processing_latency_ms": _ms(started),
                "analysis": analysis,
            }
            try:
                self.sink(payload)
                published = True
            except Exception:  # pragma: no cover - sink failures never break ingestion
                logger.exception("evidence sink failed for %s", event.event_id)

        with self._lock:
            self.processed += 1
            if published:
                self.published += 1

        return ProcessingResult(
            event_id=event.event_id,
            transaction_id=event.transaction_id,
            accepted=True,
            action=result.action,
            analysis=analysis,
            published=published,
            elapsed_ms=_ms(started),
            graph_version=result.graph_version,
            detail=result.detail,
        )

    # alias used by the HTTP ingestion route (counter only, no re-analysis)
    on_event = process

    # ------------------------------------------------------------------ #
    def _fast_analysis(self, event: TransactionEvent) -> dict[str, Any]:
        """Profile FAST: fan signals + window counts + graph facts."""
        account = event.destination_account
        from ..graph.adjacency_index import Window

        from ..algorithms.fan_detection import fan_result_to_pattern

        resolved = Window.preset("5m", reference=event.timestamp)
        fan_in = detect_fan_in(self.store, account, resolved)
        fan_out = detect_fan_out(self.store, account, resolved)

        facts = [
            graph_fact(
                label="EVENT_INGESTED",
                details={
                    "transaction_id": event.transaction_id,
                    "source": event.source_account,
                    "destination": event.destination_account,
                    "amount": event.amount,
                    "timestamp": event.timestamp,
                    "status": event.status.value,
                },
                explanation="Transaction event observed and indexed in the graph.",
                transaction_ids=[event.transaction_id],
                source="event_processor",
            )
        ]
        pattern_objs = [fan_result_to_pattern(p) for p in (fan_in, fan_out)]
        pattern_objs = [p for p in pattern_objs if p is not None]

        risk = assess(
            account,
            self.store,
            fan_in=fan_in,
            fan_out=fan_out,
            patterns=pattern_objs,
        )
        evidence = build_evidence_bundle(facts, pattern_objs, [], anchor=event.event_id[:12])
        window_counts = self.windows.counts(account, now=event.timestamp)

        return {
            "profile": "FAST",
            "target_account": account,
            "fan_in": fan_in.to_dict(),
            "fan_out": fan_out.to_dict(),
            "window_counts": window_counts,
            "risk_assessment": risk.to_dict(),
            "graph_evidence": evidence,
            "evidence_digest": evidence_digest(evidence),
            "patterns_detected": len(pattern_objs),
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "processed": self.processed,
                "published": self.published,
                "windows": self.windows.stats(),
            }


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)


class CollectingSink:
    """In-memory sink used by tests and the local simulator."""

    def __init__(self, limit: int = 10_000) -> None:
        self.items: list[dict[str, Any]] = []
        self.limit = limit
        self._lock = threading.Lock()

    def __call__(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.items.append(payload)
            if len(self.items) > self.limit:
                del self.items[: len(self.items) - self.limit]

    def latest(self, n: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.items[-n:])
