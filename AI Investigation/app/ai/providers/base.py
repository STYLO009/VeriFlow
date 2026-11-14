"""Provider contract shared by the Gemini and Hugging Face adapters.

Both adapters translate the *same* internal request/response shapes into
their wire format, which is what guarantees that a provider switch never
changes the system instructions, tool contracts or output schemas seen by
the model.
"""

from __future__ import annotations

import abc
import enum
from dataclasses import dataclass, field
from typing import Any, Literal


class ProviderId(str, enum.Enum):
    GEMINI = "gemini"
    HUGGINGFACE = "huggingface"


class ProviderErrorKind(str, enum.Enum):
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    SERVER_ERROR = "server_error"
    UNAVAILABLE = "unavailable"
    AUTH = "auth"
    CONFIG = "config"
    REQUEST = "request"
    INVALID_RESPONSE = "invalid_response"
    BLOCKED = "content_blocked"
    UNKNOWN = "unknown"


# Errors that justify retrying the same provider, then falling back to the
# next one. AUTH / CONFIG / REQUEST are deliberately *not* retried: they are
# surfaced immediately (never silently hidden) and recorded as switches.
RETRYABLE_KINDS: frozenset[ProviderErrorKind] = frozenset(
    {
        ProviderErrorKind.RATE_LIMIT,
        ProviderErrorKind.TIMEOUT,
        ProviderErrorKind.SERVER_ERROR,
        ProviderErrorKind.UNAVAILABLE,
        ProviderErrorKind.INVALID_RESPONSE,
    }
)


@dataclass
class ProviderError(Exception):
    """Structured provider failure."""

    provider: str
    kind: ProviderErrorKind
    message: str
    status_code: int | None = None
    retryable: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.retryable = self.kind in RETRYABLE_KINDS

    def __str__(self) -> str:  # pragma: no cover - trivial
        code = f" (HTTP {self.status_code})" if self.status_code else ""
        return f"{self.provider}: {self.kind.value}{code}: {self.message}"


class AllProvidersUnavailable(Exception):
    """Raised when every configured provider failed (never swallowed)."""

    def __init__(self, errors: list[ProviderError]) -> None:
        self.errors = errors
        detail = "; ".join(str(e) for e in errors) or "no provider configured"
        super().__init__(f"all AI providers unavailable: {detail}")


class NoProviderConfigured(Exception):
    """Raised when the deployment has no AI provider key at all."""


@dataclass
class ProviderToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ProviderToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ProviderRequest:
    messages: list[ProviderMessage]
    tools: list[ToolDefinition] = field(default_factory=list)
    temperature: float = 0.1
    max_tokens: int = 4096
    json_response: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ProviderResponse:
    provider: str
    model: str
    text: str = ""
    tool_calls: list[ProviderToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: ProviderUsage = field(default_factory=ProviderUsage)
    latency_ms: float = 0.0
    raw_excerpt: str = ""


@dataclass
class ProviderSwitch:
    """One recorded provider change. Never hidden from callers/reports."""

    provider: str
    reason: ProviderErrorKind
    message: str
    at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "reason": self.reason.value,
            "message": self.message,
            "at": self.at,
        }


class ProviderAdapter(abc.ABC):
    """Base class for independent provider adapters."""

    id: str = "abstract"
    role: str = "primary"  # primary | secondary

    def __init__(self, model: str, timeout_s: float = 45.0) -> None:
        self.model = model
        self.timeout_s = timeout_s

    @property
    @abc.abstractmethod
    def configured(self) -> bool:
        """True when credentials are present (not a health probe)."""

    @abc.abstractmethod
    async def complete(self, request: ProviderRequest) -> ProviderResponse:
        """Execute one chat completion; raises ProviderError on failure."""

    async def aclose(self) -> None:  # pragma: no cover - default no-op
        return None

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "model": self.model,
            "configured": self.configured,
            "timeout_s": self.timeout_s,
        }


__all__ = [
    "AllProvidersUnavailable",
    "NoProviderConfigured",
    "ProviderAdapter",
    "ProviderError",
    "ProviderErrorKind",
    "ProviderId",
    "ProviderMessage",
    "ProviderRequest",
    "ProviderResponse",
    "ProviderSwitch",
    "ProviderToolCall",
    "ProviderUsage",
    "RETRYABLE_KINDS",
    "ToolDefinition",
]
