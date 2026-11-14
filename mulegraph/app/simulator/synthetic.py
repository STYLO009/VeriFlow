"""Deterministic synthetic transaction generator.

Reproducible (seeded) and scenario-aware: it emits normal peer-to-peer traffic
plus attack patterns (fan-in, fan-out, cycles, chains, duplicates, late
events, status changes) so tests and benchmarks are meaningful.

Timeline model: events are generated with timestamps spaced by
``1 / events_per_second`` starting at ``start_ts``, so a "50 TPS" run really
processes 50 events per simulated second while remaining fully deterministic.
"""

from __future__ import annotations

import random
import string
from dataclasses import dataclass, field
from typing import Iterator

from ..graph.models import TransactionEvent, TransactionStatus

# scenario weights (must sum to 1.0)
SCENARIO_WEIGHTS: dict[str, float] = {
    "normal": 0.62,
    "fan_in": 0.08,
    "fan_out": 0.08,
    "cycle": 0.07,
    "chain": 0.07,
    "duplicate": 0.03,
    "late": 0.03,
    "status_change": 0.02,
    "reversed": 0.01,
    "held": 0.01,
}


@dataclass
class SyntheticTransactionGenerator:
    """Seeded generator producing :class:`TransactionEvent` objects."""

    seed: int = 42
    events_per_second: float = 100.0
    start_ts: float = 1_700_000_000.0
    account_pool_size: int = 500
    scenario_weights: dict[str, float] = field(default_factory=lambda: dict(SCENARIO_WEIGHTS))

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._accounts = [f"ACC-{i:04d}" for i in range(self.account_pool_size)]
        # a few "hub" accounts that receive/emit more traffic
        self._hubs = self._accounts[:10]
        self._index = 0
        self._clock = self.start_ts
        self._step = 1.0 / max(1.0, self.events_per_second)
        self._last_events: list[TransactionEvent] = []
        self._cycle_positions: dict[str, int] = {}
        self._chain_buffer: list[str] = []
        # attacker rings reused across events for realistic clustering
        self._fan_in_target = "ACC-0901"
        self._fan_out_source = "ACC-0902"
        self._ring_a = [f"ACC-{i:04d}" for i in range(900, 950)]
        self._ring_b = [f"ACC-{i:04d}" for i in range(950, 999)]

    # ------------------------------------------------------------------ #
    def _next_account(self) -> str:
        return self._rng.choice(self._accounts)

    def _next_id(self, prefix: str = "TX") -> str:
        self._index += 1
        return f"{prefix}-{self._index:08d}"

    def _event(
        self,
        src: str,
        dst: str,
        amount: float,
        ts: float | None = None,
        status: TransactionStatus = TransactionStatus.COMPLETED,
        event_type: str = "TRANSACTION",
        event_id: str | None = None,
        transaction_id: str | None = None,
        metadata: dict | None = None,
    ) -> TransactionEvent:
        ts = self._clock if ts is None else ts
        tx = transaction_id or self._next_id()
        return TransactionEvent(
            event_id=event_id or f"EVT-{tx}-{event_type}",
            transaction_id=tx,
            source_account=src,
            destination_account=dst,
            amount=round(amount, 2),
            timestamp=ts,
            status=status,
            event_type=event_type,
            metadata=metadata or {},
        )

    # ------------------------------------------------------------------ #
    def next_event(self) -> TransactionEvent:
        """Advance the simulated clock and emit one event."""
        self._clock += self._step
        scenario = self._rng.choices(
            list(self.scenario_weights), weights=list(self.scenario_weights.values())
        )[0]
        handler = getattr(self, f"_scenario_{scenario}", self._scenario_normal)
        event = handler()
        self._remember(event)
        return event

    def generate(self, count: int) -> Iterator[TransactionEvent]:
        for _ in range(count):
            yield self.next_event()

    def _remember(self, event: TransactionEvent) -> None:
        self._last_events.append(event)
        if len(self._last_events) > 64:
            del self._last_events[:-64]

    # ------------------------------------------------------------------ #
    # scenarios
    # ------------------------------------------------------------------ #
    def _scenario_normal(self) -> TransactionEvent:
        src = self._next_account()
        dst = self._next_account()
        while dst == src:
            dst = self._next_account()
        # occasionally involve a hub
        if self._rng.random() < 0.25:
            dst = self._rng.choice(self._hubs)
        return self._event(src, dst, self._rng.uniform(50, 20_000))

    def _scenario_fan_in(self) -> TransactionEvent:
        """Many distinct accounts -> one common target (within seconds)."""
        source = self._rng.choice(self._ring_a)
        return self._event(source, self._fan_in_target, self._rng.uniform(5_000, 60_000))

    def _scenario_fan_out(self) -> TransactionEvent:
        """One source -> many distinct destinations (burst)."""
        dest = self._rng.choice(self._ring_b)
        return self._event(self._fan_out_source, dest, self._rng.uniform(5_000, 60_000))

    def _scenario_cycle(self) -> TransactionEvent:
        """A -> B -> C -> A loop executed edge by edge."""
        loop = ["ACC-0801", "ACC-0802", "ACC-0803"]
        pos = self._cycle_positions.get("main", 0)
        src = loop[pos % len(loop)]
        dst = loop[(pos + 1) % len(loop)]
        self._cycle_positions["main"] = pos + 1
        return self._event(src, dst, self._rng.uniform(10_000, 40_000))

    def _scenario_chain(self) -> TransactionEvent:
        """Rapid sequential transfers a -> b -> c -> d."""
        if len(self._chain_buffer) < 2:
            self._chain_buffer = [self._next_account() for _ in range(4)]
        src = self._chain_buffer[0]
        dst = self._chain_buffer[1]
        self._chain_buffer = self._chain_buffer[1:]
        return self._event(src, dst, self._rng.uniform(20_000, 80_000))

    def _scenario_duplicate(self) -> TransactionEvent:
        """Exact redelivery of a previous event (dedupe test)."""
        if not self._last_events:
            return self._scenario_normal()
        previous = self._rng.choice(self._last_events)
        # same event id, same transaction - must be rejected by the pipeline
        return previous.model_copy(update={"timestamp": self._clock})

    def _scenario_late(self) -> TransactionEvent:
        """Event arriving with an old timestamp (out-of-order delivery)."""
        late_offset = self._rng.uniform(1.0, 60.0)
        event = self._scenario_normal()
        return event.model_copy(update={"timestamp": self._clock - late_offset})

    def _scenario_status_change(self) -> TransactionEvent:
        """STATUS_UPDATE: COMPLETED -> REVERSED on a previous transaction."""
        candidates = [e for e in self._last_events if e.event_type == "TRANSACTION"]
        if not candidates:
            return self._scenario_normal()
        base = self._rng.choice(candidates)
        return self._event(
            src=base.source_account,
            dst=base.destination_account,
            amount=base.amount,
            status=TransactionStatus.REVERSED,
            event_type="STATUS_UPDATE",
            event_id=f"EVT-{base.transaction_id}-REVERSED",
            transaction_id=base.transaction_id,
        )

    def _scenario_reversed(self) -> TransactionEvent:
        """New transaction that starts in REVERSED state."""
        event = self._scenario_normal()
        return event.model_copy(update={"status": TransactionStatus.REVERSED})

    def _scenario_held(self) -> TransactionEvent:
        """New transaction held for verification (must not count as flow)."""
        event = self._scenario_normal()
        return event.model_copy(update={"status": TransactionStatus.HELD_FOR_VERIFICATION})


def random_account_id(rng: random.Random | None = None) -> str:
    rng = rng or random.Random()
    suffix = "".join(rng.choices(string.digits, k=6))
    return f"ACC-{suffix}"
