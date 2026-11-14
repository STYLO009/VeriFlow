"""AI investigation service: the facade used by the FastAPI router.

Owns the provider chain, tool registry, graph client, prompts, audit log,
cache, session store and LangGraph runner, and exposes:

* ``investigate``      - autonomous investigation -> strict report
* ``chat``             - interactive investigator conversation
* ``investigate_stream`` - SSE progress events + final report
* ``get_investigation`` / ``get_report``
* ``providers_status`` / ``health``
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator, Callable

from .audit import AuditLog
from .config import AIConfig
from .prompting import PromptLibrary
from .providers import (
    AllProvidersUnavailable,
    GeminiAdapter,
    HuggingFaceAdapter,
    NoProviderConfigured,
    ProviderManager,
    ProviderMessage,
    ProviderRequest,
)
from .schemas import (
    ChatRequest,
    ChatResponse,
    InvestigationSummary,
)
from .tools import GraphClient, ToolRegistry, ToolResultCache, build_default_registry, create_graph_client
from .tools.validation import ToolValidationError, validate_question
from .workflow import (
    AIContext,
    InvestigationRunner,
    InvestigationState,
    InvestigationStore,
    WorkflowFailure,
    new_investigation_state,
)

logger = logging.getLogger("mulegraph.ai.service")


class InvestigationFailed(Exception):
    """An investigation aborted before a report could be produced."""

    def __init__(self, message: str, state: dict[str, Any]) -> None:
        self.state = state
        self.investigation_id = state.get("investigation_id")
        super().__init__(message)


class AIService:
    def __init__(
        self,
        services: dict[str, Any] | None = None,
        config: AIConfig | None = None,
        *,
        providers: ProviderManager | None = None,
        client: GraphClient | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.config = config or AIConfig.from_env()
        self.engine_services = services or {}
        self.audit = AuditLog(self.config.audit_path)
        self.cache = ToolResultCache(
            enabled=self.config.cache_enabled, ttl_s=30.0, max_entries=256
        )
        self.store = InvestigationStore(
            state_dir=self.config.state_dir, max_items=self.config.max_investigations
        )
        self.loaded_persisted = self.store.load_all()
        self.prompts = PromptLibrary()
        self.registry = registry or build_default_registry()
        self.client = client or create_graph_client(services, self.config)
        self.providers = providers or self._build_providers()
        self.ctx = AIContext(
            config=self.config,
            providers=self.providers,
            registry=self.registry,
            client=self.client,
            prompts=self.prompts,
            audit=self.audit,
            cache=self.cache,
        )
        self.runner = InvestigationRunner(self.ctx)
        self._runs: dict[str, asyncio.Task[None]] = {}

    # ------------------------------------------------------------------ #
    def _build_providers(self) -> ProviderManager:
        adapters = [
            GeminiAdapter(
                api_key=self.config.gemini_api_key,
                model=self.config.gemini_model,
                base_url=self.config.gemini_base_url,
                timeout_s=self.config.request_timeout_s,
            ),
            HuggingFaceAdapter(
                api_key=self.config.huggingface_api_key,
                model=self.config.huggingface_model,
                base_url=self.config.huggingface_base_url,
                timeout_s=self.config.request_timeout_s,
            ),
        ]
        return ProviderManager(adapters, self.config)

    async def aclose(self) -> None:
        await self.providers.aclose()
        self.client.close()

    # ------------------------------------------------------------------ #
    # autonomous investigation
    # ------------------------------------------------------------------ #
    def _initial_state(
        self,
        *,
        account_ids: list[str] | None = None,
        transaction_ids: list[str] | None = None,
        question: str | None = None,
        objective: str | None = None,
        use_case: str = "auto",
        time_window: str | None = None,
        profile: str | None = None,
        session_id: str | None = None,
        max_tool_calls: int | None = None,
        max_steps: int | None = None,
    ) -> InvestigationState:
        return new_investigation_state(
            account_ids=account_ids,
            transaction_ids=transaction_ids,
            question=question,
            objective=objective,
            use_case=use_case,
            time_window=time_window or self.config.default_time_window,
            profile=profile or self.config.default_profile,
            session_id=session_id,
            max_tool_calls=max_tool_calls or self.config.max_tool_calls,
            max_steps=max_steps or self.config.max_steps,
            max_wall_clock_s=self.config.max_wall_clock_s,
        )

    async def investigate(
        self,
        *,
        account_ids: list[str] | None = None,
        transaction_ids: list[str] | None = None,
        question: str | None = None,
        objective: str | None = None,
        use_case: str = "auto",
        time_window: str | None = None,
        profile: str | None = None,
        session_id: str | None = None,
        max_tool_calls: int | None = None,
        max_steps: int | None = None,
    ) -> dict[str, Any]:
        self._require_provider()
        state = self._initial_state(
            account_ids=account_ids,
            transaction_ids=transaction_ids,
            question=resolve_question_text(question),
            objective=objective,
            use_case=use_case,
            time_window=time_window,
            profile=profile,
            session_id=session_id,
            max_tool_calls=max_tool_calls,
            max_steps=max_steps,
        )
        return await self._run(state)

    async def _run(
        self,
        state: InvestigationState,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        investigation_id = state.get("investigation_id") or ""
        self.audit.record(
            "investigation_start",
            investigation_id,
            use_case=state.get("use_case"),
            targets=state.get("target_account_ids", [])
            + state.get("target_transaction_ids", []),
        )
        try:
            final = await self.runner.run(state, on_event=on_event)
        except WorkflowFailure as exc:
            self.store.save(exc.state)
            raise InvestigationFailed(str(exc), exc.state) from exc
        except AllProvidersUnavailable as exc:
            # preserve whatever the investigation already collected
            partial = getattr(exc, "partial_state", None)
            if isinstance(partial, dict) and partial.get("investigation_id"):
                self.store.save(partial)
            raise
        except NoProviderConfigured:
            raise
        self.store.save(final)
        return final

    # ------------------------------------------------------------------ #
    # streaming investigation (SSE)
    # ------------------------------------------------------------------ #
    async def investigate_stream(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        """Yield progress events, then a final ``completed`` event with report."""
        self._require_provider()
        state = self._initial_state(
            account_ids=kwargs.get("account_ids"),
            transaction_ids=kwargs.get("transaction_ids"),
            question=resolve_question_text(kwargs.get("question")),
            objective=kwargs.get("objective"),
            use_case=kwargs.get("use_case", "auto"),
            time_window=kwargs.get("time_window"),
            profile=kwargs.get("profile"),
            session_id=kwargs.get("session_id"),
            max_tool_calls=kwargs.get("max_tool_calls"),
            max_steps=kwargs.get("max_steps"),
        )
        inv_id = state.get("investigation_id") or ""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        yield {"type": "started", "investigation_id": inv_id, "at": time.time()}
        try:
            final = await self._run(state, on_event=queue.put_nowait)
        except (NoProviderConfigured,) as exc:
            yield {"type": "error", "code": "NO_PROVIDER", "message": str(exc)}
            return
        except InvestigationFailed as exc:
            yield {
                "type": "error",
                "code": "INVESTIGATION_FAILED",
                "message": str(exc),
                "investigation_id": inv_id,
            }
            return
        except Exception as exc:  # noqa: BLE001 - stream must terminate cleanly
            yield {"type": "error", "code": "PROVIDERS_UNAVAILABLE", "message": str(exc)}
            return

        while not queue.empty():
            yield queue.get_nowait()
        yield {
            "type": "completed",
            "investigation_id": inv_id,
            "status": final.get("execution_status"),
            "report": final.get("final_report"),
        }

    # ------------------------------------------------------------------ #
    # interactive chat
    # ------------------------------------------------------------------ #
    async def chat(self, request: ChatRequest) -> ChatResponse:
        self._require_provider()
        question = resolve_question_text(request.message)
        if question is None:
            raise ValueError("chat message cannot be empty")
        state: dict[str, Any] | None = None
        if request.investigation_id:
            state = self.store.get(request.investigation_id)
        if state is None and request.session_id:
            state = self.store.by_session(request.session_id)

        created_new = False
        if state is None or not state.get("final_report"):
            if state is None:
                state = dict(
                    self._initial_state(
                        account_ids=request.account_ids,
                        question=question,
                        use_case="auto",
                        time_window=request.time_window,
                        session_id=request.session_id,
                    )
                )
                created_new = True
                final = await self._run(state)  # type: ignore[arg-type]
                state = final
            else:
                # an unfinished investigation: resume it instead of restarting
                final = await self._run(state)  # type: ignore[arg-type]
                state = final

        answer, refs, tools_used = await self._answer_question(state, question)
        state = self.store.save({**state, "answer": answer})
        return ChatResponse(
            investigation_id=str(state.get("investigation_id", "")),
            answer=answer,
            evidence_refs=refs,
            provider_used=str(state.get("provider_used") or ""),
            tools_used=tools_used,
            investigation_status=state.get("execution_status", "completed"),  # type: ignore[arg-type]
            created_new_investigation=created_new,
        )

    async def _answer_question(
        self, state: dict[str, Any], question: str
    ) -> tuple[str, list[str], list[str]]:
        """Grounded answer; may run a small bounded round of extra tools."""
        fx = _EffectsLite()
        report = state.get("final_report") or {}
        context = {
            "question": question,
            "objective": state.get("investigation_objective"),
            "evidence_strength": report.get("evidence_strength")
            or state.get("_evidence_strength", "insufficient"),
            "executive_summary": report.get("executive_summary", ""),
            "observed_facts": [
                f.get("statement") for f in (report.get("observed_facts") or state.get("_observed_facts", []))[:25]
            ],
            "detected_patterns": [
                {"type": p.get("pattern_type"), "summary": p.get("summary")}
                for p in (report.get("detected_patterns") or state.get("_detected_patterns", []))[:15]
            ],
            "involved_accounts": [
                a.get("account_id")
                for a in (report.get("involved_accounts") or state.get("_involved_accounts", []))[:30]
            ],
            "money_flow_paths": (report.get("money_flow_paths") or [])[:5],
            "supporting_metrics": report.get("supporting_metrics", {}),
            "limitations": (report.get("limitations") or [])[:6],
        }
        system = self.prompts.get("chat")
        user = json.dumps(context, default=str, indent=1)

        tools = self.registry.definitions()
        request = ProviderRequest(
            messages=[
                ProviderMessage(role="system", content=system),
                ProviderMessage(role="user", content=user),
            ],
            tools=tools,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            metadata={"stage": "chat", "investigation_id": state.get("investigation_id", "")},
        )
        result = await self.providers.complete(request)
        for switch in result.switches:
            fx.switches.append(switch.to_dict())
        if result.response.tool_calls:
            # bounded extra tool round, then final answer without tools
            executed = 0
            tool_msgs = list(request.messages)
            tool_msgs.append(
                ProviderMessage(
                    role="assistant",
                    content=result.response.text,
                    tool_calls=result.response.tool_calls,
                )
            )
            for call in result.response.tool_calls[: self.config.chat_max_extra_tool_calls]:
                tool_result = await asyncio.to_thread(
                    lambda c=call: self.registry.invoke(
                        c.name, c.arguments, self.client, self.config.tool_result_char_budget
                    )
                )
                fx.tools_used.append(tool_result.tool)
                fx.tool_history.append(tool_result.to_history())
                if tool_result.ok:
                    fx.evidence.append(_chat_evidence_record(tool_result, self.registry, len(fx.evidence)))
                tool_msgs.append(
                    ProviderMessage(
                        role="tool",
                        content=json.dumps(
                            {"ok": tool_result.ok, "error": tool_result.error, "data": tool_result.data},
                            default=str,
                        ),
                        tool_call_id=call.id,
                        name=call.name,
                    )
                )
                executed += 1
            followup = ProviderRequest(
                messages=tool_msgs,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                metadata={"stage": "chat_final", "investigation_id": state.get("investigation_id", "")},
            )
            result = await self.providers.complete(followup)
            for switch in result.switches:
                fx.switches.append(switch.to_dict())

        answer = (result.response.text or "").strip()
        if not answer:
            answer = (
                "The model returned an empty answer. See the investigation report "
                "for the evidence collected so far."
            )
        refs: list[str] = []
        if "EVIDENCE:" in answer:
            body, _, tail = answer.rpartition("EVIDENCE:")
            answer = body.strip()
            refs = [r.strip() for r in tail.replace("\n", ",").split(",") if r.strip()][:30]
        # persist chat effects into the stored investigation
        if fx.switches or fx.tool_history:
            updated = dict(state)
            history = list(updated.get("tool_execution_history", [])) + fx.tool_history
            evidence = list(updated.get("evidence_collection", [])) + fx.evidence
            fallback = list(updated.get("fallback_history", [])) + fx.switches
            updated.update(
                {
                    "tool_execution_history": history,
                    "evidence_collection": evidence,
                    "fallback_history": fallback,
                    "provider_used": result.provider,
                    "updated_at": time.time(),
                }
            )
            self.store.save(updated)
        return answer, refs, fx.tools_used

    # ------------------------------------------------------------------ #
    # reads
    # ------------------------------------------------------------------ #
    def get_investigation(self, investigation_id: str) -> dict[str, Any]:
        state = self.store.get(investigation_id)
        if state is None:
            raise KeyError(investigation_id)
        evidence = state.get("evidence_collection", [])
        summary = InvestigationSummary(
            investigation_id=investigation_id,
            status=str(state.get("execution_status", "pending")),
            objective=str(state.get("investigation_objective", "")),
            use_case=str(state.get("use_case", "")),
            target_accounts=list(state.get("target_account_ids", [])),
            target_transaction_ids=list(state.get("target_transaction_ids", [])),
            investigation_steps=int(state.get("investigation_steps", 0) or 0),
            tool_call_count=int(state.get("tool_call_count", 0) or 0),
            provider_used=str(state.get("provider_used", "")),
            providers_used=list(state.get("providers_used", [])),
            fallback_history=list(state.get("fallback_history", [])),
            execution_status=str(state.get("execution_status", "pending")),
            report_ready=bool(state.get("final_report")),
            started_at=state.get("started_at"),
            updated_at=state.get("updated_at"),
            evidence_counts={
                "evidence_items": len(evidence),
                "successful": sum(1 for e in evidence if e.get("ok")),
                "failed": sum(1 for e in evidence if not e.get("ok")),
                "patterns": len(state.get("_detected_patterns", [])),
                "paths": len(state.get("_money_flow_paths", [])),
                "contradictions": len(state.get("contradictions", [])),
            },
        )
        return summary.model_dump()

    def get_report(self, investigation_id: str) -> dict[str, Any]:
        state = self.store.get(investigation_id)
        if state is None:
            raise KeyError(investigation_id)
        report = state.get("final_report")
        if not report:
            raise ValueError(f"investigation {investigation_id} has no report yet")
        return report

    # ------------------------------------------------------------------ #
    # operational
    # ------------------------------------------------------------------ #
    def providers_status(self) -> dict[str, Any]:
        status = self.providers.status()
        return {
            "providers": status["providers"],
            "active_order": status["active_order"],
            "any_configured": status["any_configured"],
            "config": self.config.redacted(),
            "recent_switches": status["recent_switches"],
        }

    def health(self) -> dict[str, Any]:
        status = self.providers.status()
        configured = [p for p in status["providers"] if p["configured"]]
        failing = [p for p in configured if p.get("healthy") is False]
        if not configured:
            state = "unavailable"
            detail = "no AI provider configured (set GEMINI_API_KEY and/or HF_API_KEY)"
        elif configured and len(failing) == len(configured) and failing:
            state = "degraded"
            detail = "; ".join(
                f"{p['id']}: {p.get('last_error_kind') or 'error'}" for p in failing
            )
        else:
            state = "ok"
            detail = f"{len(configured)} provider(s) configured"
        graph_version: int | None = None
        try:
            graph_version_raw = self.client.health().get("graph_version")
            if graph_version_raw is not None:
                graph_version = int(graph_version_raw)
        except Exception:  # noqa: BLE001
            graph_version = None
        return {
            "status": state,
            "providers_configured": bool(configured),
            "providers_available": len(configured) - len(failing),
            "graph_version": graph_version,
            "graph_backend": self.client.backend,
            "investigations_tracked": len(self.store),
            "detail": detail,
        }

    def audit_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.audit.recent(limit)

    # ------------------------------------------------------------------ #
    def _require_provider(self) -> None:
        if not self.config.any_provider_configured:
            raise NoProviderConfigured(
                "no AI provider configured: set GEMINI_API_KEY (primary) and/or "
                "HF_API_KEY (secondary); /api/v1/ai/providers/status shows the details"
            )


class _EffectsLite:
    """Small collector for chat-time provider/tool effects."""

    def __init__(self) -> None:
        self.switches: list[dict[str, Any]] = []
        self.tools_used: list[str] = []
        self.tool_history: list[dict[str, Any]] = []
        self.evidence: list[dict[str, Any]] = []


def resolve_question_text(text: str | None) -> str | None:
    """Sanitise an investigator question; rejects empty/control-char payloads."""
    if text is None:
        return None
    try:
        return validate_question(text)
    except ToolValidationError as exc:
        raise ValueError(str(exc)) from exc


def _chat_evidence_record(result: Any, registry: ToolRegistry, seq: int) -> dict[str, Any]:
    spec = registry.get(result.tool)
    fact = ""
    if spec and spec.fact_builder and isinstance(result.data, dict):
        try:
            fact = spec.fact_builder(result.data, result.arguments)
        except Exception:  # noqa: BLE001
            fact = ""
    return {
        "evidence_id": f"EV-{result.tool}-chat-{seq:03d}",
        "tool": result.tool,
        "arguments": result.arguments,
        "ok": result.ok,
        "summary": fact,
        "data": result.data,
        "transaction_ids": result.transaction_ids,
        "account_ids": result.account_ids[:80],
        "graph_version": result.graph_version,
        "collected_at": result.collected_at,
        "provenance": result.provenance,
        "cached": result.cached,
    }


def create_ai_service(
    services: dict[str, Any] | None = None, config: AIConfig | None = None, **kwargs: Any
) -> AIService:
    return AIService(services, config, **kwargs)


__all__ = ["AIService", "InvestigationFailed", "create_ai_service"]
