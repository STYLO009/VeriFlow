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

import json
import logging
import time
from typing import Any, Iterable, Iterator

from ..graph.models import TransactionEvent, TransactionStatus
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


class RedisEventSource:
    """Redis Streams event source for authoritative transaction outcomes.

    Node.js publishes outcome events to Redis with JSON payloads under key
    ``event``. This source polls the stream with a consumer group, maps each
    message into a :class:`TransactionEvent`, and acks the message after
    successful graph processing.

    Redis is an optional dependency: the source only connects when instantiated.
    """

    def __init__(
        self,
        url: str,
        stream: str,
        group: str,
        consumer: str,
        max_attempts: int = 5,
        backoff_ms: float = 1000.0,
    ) -> None:
        try:
            import redis as redis_py  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "RedisEventSource requires redis: pip install redis"
            ) from exc
        self._redis_module = redis_py
        self._client = redis_py.Redis.from_url(url, decode_responses=True)
        self._stream = stream
        self._group = group
        self._consumer = consumer
        self._max_attempts = max_attempts
        self._backoff_ms = backoff_ms
        self._running = False
        self._retry_keys: dict[str, int] = {}

    def connect(self) -> None:
        """Ensure the consumer group exists (creates it with MKSTREAM)."""
        self._client.ping()
        try:
            self._client.xgroup_create(self._stream, self._group, id="0-0", mkstream=True)
        except self._redis_module.exceptions.ResponseError as exc:  # type: ignore[attr-defined]
            if "BUSYGROUP" not in str(exc):
                raise

    def close(self) -> None:
        self._running = False
        self._client.close()

    def _parse_event(self, payload: dict[str, str]) -> TransactionEvent:
        event = json.loads(payload.get("event", "{}"))
        status = TransactionStatus.COMPLETED
        raw_status = event.get("status")
        if raw_status:
            try:
                status = TransactionStatus(raw_status.upper())
            except ValueError:
                status = TransactionStatus.COMPLETED
        return TransactionEvent(
            event_id=event.get("eventRef", payload.get("eventRef", "unknown")),
            transaction_id=event.get("transactionRef", event.get("transactionId", "unknown")),
            source_account=event.get("senderId", ""),
            destination_account=event.get("receiverId", ""),
            amount=float(event.get("amountPaise", event.get("amount", 0))) / 100.0,
            currency=event.get("currency", "INR"),
            timestamp=event.get("occurredAt", time.time()),
            status=status,
            event_type="STATUS_UPDATE",
        )

    def poll(self, batch_size: int = 100) -> list[TransactionEvent]:
        """Poll the Redis stream with consumer-group semantics.

        New messages are read with ``XREADGROUP``. Pending messages are
        reclaimed with ``XAUTOCLAIM`` after the configured backoff. Messages
        that exceed ``max_attempts`` are moved to the dead-letter stream and
        acked so they cannot block the group.
        """
        if not self._running:
            return []

        events: list[TransactionEvent] = []
        now_ms = time.time() * 1000

        # Reclaim pending messages that have been idle past backoff.
        try:
            claimed = self._client.xautoclaim(
                self._stream,
                self._group,
                self._consumer,
                min_idle_time=int(self._backoff_ms),
                start_id="0-0",
                count=batch_size,
            )
        except Exception:  # pragma: no cover - stream may be empty
            claimed = []

        claimed_messages = claimed[1] if len(claimed) > 1 else []
        for msg_id, fields in claimed_messages:
            event = self._parse_event(fields)
            attempts = self._retry_keys.get(msg_id, 0) + 1
            self._retry_keys[msg_id] = attempts
            if attempts >= self._max_attempts:
                try:
                    self._client.xadd(
                        f"{self._stream}:dead-letter",
                        {"original_id": msg_id, "payload": fields.get("event", ""), "attempts": str(attempts)},
                    )
                except Exception:  # pragma: no cover - best effort
                    pass
                self._client.xack(self._stream, self._group, msg_id)
                self._retry_keys.pop(msg_id, None)
                logger.warning("Redis message %s moved to dead-letter stream", msg_id)
                continue
            events.append(event)

        # Read new messages.
        try:
            response = self._client.xreadgroup(
                self._group,
                self._consumer,
                {self._stream: ">"},
                count=batch_size,
                block=1000,
            )
        except Exception:  # pragma: no cover - transient Redis errors
            return events

        for _stream, messages in response:
            for msg_id, fields in messages:
                event = self._parse_event(fields)
                self._retry_keys[msg_id] = 1
                events.append(event)

        return events

    def ack(self, message_id: str) -> None:
        """Acknowledge a successfully processed message."""
        try:
            self._client.xack(self._stream, self._group, message_id)
        except Exception:  # pragma: no cover - best effort
            pass
        self._retry_keys.pop(message_id, None)



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
