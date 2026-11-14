"""Provider manager: primary Gemini, secondary Hugging Face, safe fallback.

Guarantees:

* Every provider switch is recorded (``ProviderSwitch``) and returned to the
  caller so configuration/auth problems are never silently hidden.
* Rate limits, timeouts, transient 5xx and outages fall back to the next
  provider; AUTH/CONFIG/REQUEST errors are surfaced and skip to the next
  provider without pointless retries.
* The *same* ``ProviderRequest`` (system instructions, tool contracts,
  output schema) is handed to whichever provider answers, so investigation
  state never needs to restart on a switch.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..config import AIConfig
from .base import (
    AllProvidersUnavailable,
    NoProviderConfigured,
    ProviderAdapter,
    ProviderError,
    ProviderErrorKind,
    ProviderRequest,
    ProviderResponse,
    ProviderSwitch,
    RETRYABLE_KINDS,
)

logger = logging.getLogger("mulegraph.ai.providers")

SleepFn = Callable[[float], Awaitable[None]]


@dataclass
class AttemptRecord:
    provider: str
    ok: bool
    kind: str
    message: str
    latency_ms: float
    attempt: int


@dataclass
class CompletionResult:
    response: ProviderResponse
    provider: str
    switches: list[ProviderSwitch] = field(default_factory=list)
    attempts: list[AttemptRecord] = field(default_factory=list)

    @property
    def used_fallback(self) -> bool:
        return any(s.provider != self.provider for s in self.switches)


@dataclass
class _ProviderStats:
    requests: int = 0
    failures: int = 0
    successes: int = 0
    last_error: str | None = None
    last_error_kind: str | None = None
    last_success_at: float | None = None
    total_latency_ms: float = 0.0
    fallback_switches_in: int = 0
    healthy: bool | None = None


class ProviderManager:
    """Ordered provider chain with recorded fallback and bounded retries."""

    def __init__(
        self,
        adapters: list[ProviderAdapter],
        config: AIConfig,
        sleep: SleepFn | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        order = [a for a in adapters if a.id in config.provider_order]
        # keep the configured order, append anything else deterministically
        ordered = sorted(
            order,
            key=lambda a: config.provider_order.index(a.id)
            if a.id in config.provider_order
            else len(config.provider_order),
        )
        self.adapters: dict[str, ProviderAdapter] = {a.id: a for a in ordered}
        self.order: list[str] = [a.id for a in ordered]
        self.config = config
        self._sleep = sleep or asyncio.sleep
        self._clock = clock or time.monotonic
        self._stats: dict[str, _ProviderStats] = {i: _ProviderStats() for i in self.order}
        self._recent_switches: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    def _ordered_adapters(self) -> list[ProviderAdapter]:
        return [self.adapters[i] for i in self.order]

    def record_switch(self, switch: ProviderSwitch) -> None:
        self._recent_switches.append(switch.to_dict())
        self._recent_switches = self._recent_switches[-50:]

    # ------------------------------------------------------------------ #
    async def complete(self, request: ProviderRequest) -> CompletionResult:
        errors: list[ProviderError] = []
        switches: list[ProviderSwitch] = []
        attempts: list[AttemptRecord] = []
        now = time.time()

        if not any(a.configured for a in self._ordered_adapters()):
            raise NoProviderConfigured(
                "no AI provider configured: set GEMINI_API_KEY (primary) and/or "
                "HF_API_KEY (secondary)"
            )

        for adapter in self._ordered_adapters():
            stats = self._stats[adapter.id]

            if not adapter.configured:
                err = ProviderError(
                    provider=adapter.id,
                    kind=ProviderErrorKind.CONFIG,
                    message=(
                        f"{adapter.id} is not configured "
                        f"(set {'GEMINI_API_KEY' if adapter.id == 'gemini' else 'HF_API_KEY'})"
                    ),
                )
                errors.append(err)
                switch = ProviderSwitch(
                    provider=adapter.id,
                    reason=ProviderErrorKind.CONFIG,
                    message=err.message,
                    at=now,
                )
                switches.append(switch)
                self.record_switch(switch)
                stats.failures += 1
                stats.last_error = err.message
                stats.last_error_kind = err.kind.value
                stats.healthy = False
                logger.warning("provider %s skipped: %s", adapter.id, err.message)
                continue

            max_attempts = 1 + max(0, self.config.max_retries_per_provider)
            for attempt in range(1, max_attempts + 1):
                started = self._clock()
                try:
                    response = await adapter.complete(request)
                except ProviderError as exc:
                    latency = (self._clock() - started) * 1000.0
                    stats.requests += 1
                    stats.failures += 1
                    stats.last_error = exc.message
                    stats.last_error_kind = exc.kind.value
                    stats.healthy = False
                    attempts.append(
                        AttemptRecord(
                            provider=adapter.id,
                            ok=False,
                            kind=exc.kind.value,
                            message=exc.message,
                            latency_ms=latency,
                            attempt=attempt,
                        )
                    )
                    retryable = exc.kind in RETRYABLE_KINDS and attempt < max_attempts
                    logger.warning(
                        "provider %s failed (%s, attempt %d/%d): %s",
                        adapter.id,
                        exc.kind.value,
                        attempt,
                        max_attempts,
                        exc.message,
                    )
                    if retryable:
                        await self._sleep(
                            self.config.retry_backoff_s * (2 ** (attempt - 1))
                        )
                        continue
                    errors.append(exc)
                    # permanent for this provider: record the switch reason
                    switch = ProviderSwitch(
                        provider=adapter.id,
                        reason=exc.kind,
                        message=exc.message,
                        at=time.time(),
                    )
                    switches.append(switch)
                    self.record_switch(switch)
                    break  # next provider
                else:
                    latency = (self._clock() - started) * 1000.0
                    stats.requests += 1
                    stats.successes += 1
                    stats.healthy = True
                    stats.last_success_at = time.time()
                    stats.total_latency_ms += response.latency_ms or latency
                    stats.last_error = None
                    stats.last_error_kind = None
                    attempts.append(
                        AttemptRecord(
                            provider=adapter.id,
                            ok=True,
                            kind="ok",
                            message="",
                            latency_ms=response.latency_ms or latency,
                            attempt=attempt,
                        )
                    )
                    if switches:
                        # a fallback was required: record the activation too
                        inbound = ProviderSwitch(
                            provider=adapter.id,
                            reason=ProviderErrorKind.UNKNOWN,
                            message=(
                                f"activated as fallback after: "
                                + "; ".join(s.provider for s in switches)
                            ),
                            at=time.time(),
                        )
                        switches.append(inbound)
                        self.record_switch(inbound)
                        stats.fallback_switches_in += 1
                    return CompletionResult(
                        response=response,
                        provider=adapter.id,
                        switches=switches,
                        attempts=attempts,
                    )

        raise AllProvidersUnavailable(errors)

    # ------------------------------------------------------------------ #
    def status(self) -> dict[str, Any]:
        providers: list[dict[str, Any]] = []
        for pid in self.order:
            adapter = self.adapters[pid]
            stats = self._stats[pid]
            mean_latency = (
                round(stats.total_latency_ms / stats.successes, 2)
                if stats.successes
                else None
            )
            providers.append(
                {
                    "id": pid,
                    "role": adapter.role,
                    "model": adapter.model,
                    "configured": adapter.configured,
                    "healthy": stats.healthy,
                    "last_error": stats.last_error,
                    "last_error_kind": stats.last_error_kind,
                    "requests": stats.requests,
                    "failures": stats.failures,
                    "successes": stats.successes,
                    "fallback_switches_in": stats.fallback_switches_in,
                    "last_success_at": stats.last_success_at,
                    "mean_latency_ms": mean_latency,
                }
            )
        return {
            "providers": providers,
            "active_order": list(self.order),
            "any_configured": any(a.configured for a in self._ordered_adapters()),
            "recent_switches": list(self._recent_switches[-20:]),
        }

    async def aclose(self) -> None:
        for adapter in self._ordered_adapters():
            await adapter.aclose()


__all__ = [
    "AttemptRecord",
    "CompletionResult",
    "ProviderManager",
]
