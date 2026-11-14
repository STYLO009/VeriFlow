"""Investigation runner: executes the compiled LangGraph workflow.

Uses ``astream(stream_mode=["values", "updates"])`` so the runner always holds
the latest *applied* state: if the run fails (e.g. both providers go down),
the partial state - including every tool call already executed - is preserved
for persistence and later resumption instead of being lost.

Provider outages (``NoProviderConfigured`` / ``AllProvidersUnavailable``)
propagate to the service layer so callers receive an explicit error instead
of a fabricated report; partial provider fallbacks never reach this layer
because the provider manager absorbs them and records the switch in state.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from ..providers.base import AllProvidersUnavailable, NoProviderConfigured
from .graph import build_investigation_graph
from .nodes import AIContext
from .state import InvestigationState

logger = logging.getLogger("mulegraph.ai.runner")


class WorkflowFailure(Exception):
    """Wraps the failed state so the service can persist it before responding."""

    def __init__(self, failed_state: dict[str, Any]) -> None:
        self.state = failed_state
        super().__init__(failed_state.get("error") or "investigation failed")


class InvestigationRunner:
    def __init__(self, ctx: AIContext) -> None:
        self.ctx = ctx
        self._graph: Any = None

    @property
    def graph(self) -> Any:
        if self._graph is None:
            self._graph = build_investigation_graph(self.ctx)
        return self._graph

    async def run(
        self,
        state: InvestigationState,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        inv_id = state.get("investigation_id", "")
        if on_event is not None:
            self.ctx.emitters[inv_id] = on_event
        started = time.perf_counter()
        latest: dict[str, Any] = dict(state)
        try:
            async for mode, chunk in self.graph.astream(
                state,
                config={"recursion_limit": self.ctx.config.recursion_limit},
                stream_mode=["values", "updates"],
            ):
                if mode == "values" and isinstance(chunk, dict):
                    latest = chunk
                elif mode == "updates" and on_event is not None:
                    for node_name, delta in (chunk or {}).items():
                        on_event(
                            {
                                "type": "node",
                                "node": node_name,
                                "investigation_id": inv_id,
                                "at": time.time(),
                            }
                        )
        except (NoProviderConfigured, AllProvidersUnavailable) as exc:
            self.ctx.audit.record("provider_outage", inv_id)
            failed = dict(latest)
            failed.setdefault("execution_status", "failed")
            failed["error"] = "AI provider outage: see /api/v1/ai/providers/status"
            failed["updated_at"] = time.time()
            try:
                exc.partial_state = failed  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - best effort state preservation
                pass
            raise
        except Exception as exc:  # noqa: BLE001 - surface as failed investigation
            self.ctx.audit.record(
                "failure",
                inv_id,
                error_type=type(exc).__name__,
                message=str(exc)[:300],
            )
            failed = dict(latest)
            failed["execution_status"] = "failed"
            failed["error"] = f"{type(exc).__name__}: {exc}"
            failed["updated_at"] = time.time()
            raise WorkflowFailure(failed) from exc
        finally:
            self.ctx.emitters.pop(inv_id, None)

        elapsed = (time.perf_counter() - started) * 1000.0
        self.ctx.audit.record(
            "run_complete",
            inv_id,
            status=latest.get("execution_status"),
            steps=latest.get("investigation_steps"),
            tool_calls=latest.get("tool_call_count"),
            duration_ms=round(elapsed, 2),
        )
        return latest


__all__ = ["InvestigationRunner", "WorkflowFailure"]
