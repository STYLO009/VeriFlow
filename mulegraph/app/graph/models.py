"""Core domain models for the MuleGraph engine.

The graph engine is intentionally independent of any ML / AI provider: it only
deals with transactions, accounts and graph observations.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TransactionStatus(str, Enum):
    """Lifecycle states of a transaction event."""

    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"
    HELD_FOR_VERIFICATION = "HELD_FOR_VERIFICATION"


# Only COMPLETED transactions represent settled money movement.
MONEY_TRANSFER_STATUSES: frozenset[TransactionStatus] = frozenset({TransactionStatus.COMPLETED})

# Statuses that are *observations* but must never be treated as settled flows.
NON_SETTLED_STATUSES: frozenset[TransactionStatus] = frozenset(
    {
        TransactionStatus.PENDING,
        TransactionStatus.REJECTED,
        TransactionStatus.REVERSED,
        TransactionStatus.HELD_FOR_VERIFICATION,
    }
)


def is_settled(status: TransactionStatus | str) -> bool:
    """True only for COMPLETED transactions (settled money movement)."""
    if isinstance(status, str):
        try:
            status = TransactionStatus(status)
        except ValueError:
            return False
    return status in MONEY_TRANSFER_STATUSES


def parse_timestamp(value: Any) -> float:
    """Normalise a timestamp to epoch seconds (UTC).

    Accepts numeric epoch seconds, ISO-8601 strings and ``datetime`` objects.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"Invalid timestamp: {value!r}") from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    raise ValueError(f"Unsupported timestamp type: {type(value).__name__}")


def format_timestamp(ts: float) -> str:
    """Render epoch seconds as an ISO-8601 UTC string."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class TransactionEvent(BaseModel):
    """A single transaction event arriving from a stream or API client."""

    event_id: str = Field(..., min_length=1, description="Unique id of this event (dedupe key).")
    transaction_id: str = Field(..., min_length=1, description="Unique transaction id.")
    source_account: str = Field(..., min_length=1)
    destination_account: str = Field(..., min_length=1)
    amount: float = Field(..., gt=0, description="Transaction amount (> 0).")
    currency: str = Field(default="INR", min_length=3, max_length=8)
    timestamp: float = Field(..., description="Event timestamp in epoch seconds (UTC).")
    status: TransactionStatus = Field(default=TransactionStatus.COMPLETED)
    event_type: str = Field(default="TRANSACTION", description="TRANSACTION | STATUS_UPDATE")
    metadata: dict[str, Any] = Field(default_factory=dict)

    _normalized_ts: float | None = None

    @field_validator("timestamp", mode="before")
    @classmethod
    def _coerce_timestamp(cls, value: Any) -> float:
        return parse_timestamp(value)

    @field_validator("source_account", "destination_account")
    @classmethod
    def _strip_account(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("account id must not be empty")
        return value

    @property
    def epoch(self) -> float:
        """Normalised epoch seconds for the event timestamp."""
        return self.timestamp


@dataclass
class TransactionRecord:
    """Durable view of one transaction and its full state history.

    The original event is preserved even when later status updates change the
    transaction state (e.g. COMPLETED -> REVERSED).
    """

    transaction_id: str
    source_account: str
    destination_account: str
    amount: float
    currency: str
    created_at: float
    status: TransactionStatus
    updated_at: float
    original_event: TransactionEvent
    history: list[tuple[float, TransactionStatus, str]] = field(default_factory=list)

    @property
    def is_settled(self) -> bool:
        return is_settled(self.status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "source_account": self.source_account,
            "destination_account": self.destination_account,
            "amount": self.amount,
            "currency": self.currency,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status.value,
            "is_settled": self.is_settled,
            "history": [
                {"timestamp": ts, "status": st.value, "event_id": eid}
                for ts, st, eid in self.history
            ],
        }


@dataclass
class ApplyResult:
    """Outcome of feeding one event into the graph."""

    transaction_id: str
    event_id: str
    accepted: bool
    action: str  # "created" | "status_update" | "duplicate" | "rejected"
    graph_version: int
    detail: str = ""


class GraphDomainError(Exception):
    """Base class for graph-engine errors."""


class LimitExceededError(GraphDomainError):
    """Raised when a configurable graph limit would be exceeded."""


class EventValidationError(GraphDomainError):
    """Raised when an incoming event fails validation."""
