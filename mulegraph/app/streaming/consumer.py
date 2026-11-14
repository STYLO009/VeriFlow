"""Pluggable event sources + a broker-independent stream runner.

Sources implement ``poll(batch_size) -> list[TransactionEvent]``:

* :class:`SyntheticEventSource` - deterministic local simulator (no broker)
* :class:`ListEventSource`      - in-memory list (tests)
* :class:`KafkaEventSource`     - optional Kafka/Redpanda source (only usable
  when ``kafka-python`` is installed; never required)

``run_stream`` drives any source through a :class:`GraphEventProcessor` with
rate control and graceful shutdown - the graph logic itself never imports a
broker library.
"""

from __future__ import annotations

import logging
import time
from typing import Iterable, Iterator

from ..graph.models import TransactionEvent
from .event_processor import GraphEventProcessor

logger = logging.getLogger("mulegraph.consumer")


class ListEventSource:
    """Simple source backed by an in-memory list (tests / replays)."""

    def __init__(self, events: Iterable[TransactionEvent]) -> None:
        self._events: Iterator[TransactionEvent] = iter(events)

    def poll(self, batch_size: int = 100) -> list[TransactionEvent]:
        batch: list[TransactionEvent] = []
        for _ in range(batch_size):
            try:
                batch.append(next(self._events))
            except StopIteration:
                break
        return batch


class SyntheticEventSource:
    """Endless deterministic stream from the synthetic generator."""

    def __init__(self, generator: "object", events_per_second: float = 100.0) -> None:
        """``generator`` exposes ``next_event() -> TransactionEvent``."""
        self.generator = generator
        self.events_per_second = events_per_second
        self._last_poll = 0.0

    def poll(self, batch_size: int = 100) -> list[TransactionEvent]:
        # simple pacing: emit at most events_per_second per second
        now = time.time()
        if self._last_poll:
            elapsed = now - self._last_poll
            allowed = int(elapsed * self.events_per_second) or batch_size
        else:
            allowed = batch_size
        self._last_poll = now
        count = max(1, min(batch_size, allowed))
        return [self.generator.next_event() for _ in range(count)]  # type: ignore[attr-defined]


class KafkaEventSource:
    """Optional Kafka/Redpanda consumer (requires ``kafka-python``).

    Kept in the streaming package so the graph engine stays broker-agnostic;
    importing this module does not require the dependency until instantiated.
    """

    def __init__(self, topic: str, bootstrap_servers: str = "localhost:9092", group_id: str = "mulegraph") -> None:
        try:
            from kafka import KafkaConsumer  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "KafkaEventSource requires kafka-python: pip install kafka-python"
            ) from exc
        self._consumer = KafkaConsumer(
            topic,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            value_deserializer=lambda b: TransactionEvent.model_validate_json(b),
        )

    def poll(self, batch_size: int = 100) -> list[TransactionEvent]:
        messages = self._consumer.poll(timeout_ms=200, max_records=batch_size)
        events: list[TransactionEvent] = []
        for _tp, records in messages.items():
            events.extend(r.value for r in records)
        return events

    def close(self) -> None:  # pragma: no cover
        self._consumer.close()


def run_stream(
    source: object,
    processor: GraphEventProcessor,
    duration_seconds: float | None = None,
    batch_size: int = 100,
    max_events: int | None = None,
    idle_sleep: float = 0.01,
) -> dict[str, object]:
    """Drive any event source through the processor until a stop condition.

    Returns run statistics (events, published, elapsed seconds, throughput).
    """
    started = time.perf_counter()
    total = 0
    published = 0
    try:
        while True:
            elapsed = time.perf_counter() - started
            if duration_seconds is not None and elapsed >= duration_seconds:
                break
            if max_events is not None and total >= max_events:
                break
            events = source.poll(batch_size)  # type: ignore[attr-defined]
            if not events:
                time.sleep(idle_sleep)
                continue
            for event in events:
                result = processor.process(event)
                total += 1
                published += 1 if result.published else 0
                if max_events is not None and total >= max_events:
                    break
    except KeyboardInterrupt:  # pragma: no cover - interactive use
        logger.info("stream interrupted by user")

    elapsed = time.perf_counter() - started
    return {
        "events": total,
        "published": published,
        "elapsed_seconds": round(elapsed, 3),
        "events_per_second": round(total / elapsed, 2) if elapsed > 0 else 0.0,
        "processor": processor.stats(),
    }
