"""LangGraph investigation nodes (intake, plan, act, correlate, conclude, report).

Design notes:
* Deterministic stages (intake, conclude) never call the model - observed
  facts are always derived from tool results by code.
* LLM stages return typed Pydantic outputs; malformed output gets one bounded
  repair attempt, then a deterministic fallback that never invents evidence.
* Provider failures propagate to the runner so a total outage is surfaced as
  an explicit error instead of a fabricated report; partial fallbacks are
  recorded in ``fallback_history`` and never restart the investigation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError, field_validator

from ..audit import AuditLog
from ..config import AIConfig
from ..prompting import PromptLibrary
from ..providers import (
    ProviderManager,
    ProviderMessage,
    ProviderRequest,
    ProviderResponse,
)
from ..schemas import (
    AlternativeExplanation,
    Contradiction,
    CorrelationPattern,
    InvolvedAccount,
    InvestigationPlan,
    InvestigationReport,
    MissingEvidence,
    ReasoningStep,
    RecommendedStep,
)
from ..tools import GraphClient, ToolRegistry, ToolResult, ToolResultCache, summarize_payload
from .state import InvestigationState

logger = logging.getLogger("mulegraph.ai.workflow")

Token = str


# ====================================================================== #
# helpers
# ====================================================================== #
def parse_json_block(text: str | None) -> dict[str, Any] | None:
    """Parse a JSON object out of a model response (tolerates fences/prose)."""
    if not text:
        return None
    t = text.strip()
    fence = re.match(r"^```[a-zA-Z]*\s*\n?(.*?)\n?```\s*$", t, re.DOTALL)
    if fence:
        t = fence.group(1).strip()
    try:
        data = json.loads(t)
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError):
        pass
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(t[start : end + 1])
            return data if isinstance(data, dict) else None
        except (ValueError, TypeError):
            return None
    return None


def _format_validation(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:6]:
        loc = ".".join(str(x) for x in err.get("loc", ()))
        parts.append(f"{loc}: {err.get('msg', 'invalid')}")
    return "; ".join(parts)


def _repair_message(error: str, raw: str) -> str:
    return (
        "Your previous response could not be validated and was rejected.\n"
        f"Validation problem: {error}\n"
        f"Your response started with: {raw[:800]}\n"
        "Return ONLY a corrected JSON object matching the requested schema, "
        "with no markdown and no commentary."
    )


_ACCOUNT_TOKEN = re.compile(r"\b[A-Za-z0-9][A-Za-z0-9_.:\-]{1,63}\b")


# ====================================================================== #
# node effects (delta returned to LangGraph state)
# ====================================================================== #
@dataclass
class Effects:
    """Collects append-only deltas + scalar updates for one node run."""

    validation_notes: list[str] = field(default_factory=list)
    fallback_history: list[dict[str, Any]] = field(default_factory=list)
    providers_used: list[str] = field(default_factory=list)
    tool_history: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    investigated: list[str] = field(default_factory=list)
    paths: list[dict[str, Any]] = field(default_factory=list)
    initial_evidence: list[dict[str, Any]] = field(default_factory=list)
    discovered_patterns: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    missing: list[dict[str, Any]] = field(default_factory=list)
    target_accounts: list[str] = field(default_factory=list)
    target_transactions: list[str] = field(default_factory=list)
    scalars: dict[str, Any] = field(default_factory=dict)

    def note(self, text: str) -> None:
        self.validation_notes.append(text)

    def delta(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        mapping = {
            "validation_notes": self.validation_notes,
            "fallback_history": self.fallback_history,
            "providers_used": self.providers_used,
            "tool_execution_history": self.tool_history,
            "evidence_collection": self.evidence,
            "investigated_accounts": self.investigated,
            "transaction_paths": self.paths,
            "initial_graph_evidence": self.initial_evidence,
            "discovered_patterns": self.discovered_patterns,
            "contradictions": self.contradictions,
            "alternative_explanations": self.alternatives,
            "missing_evidence": self.missing,
            "target_account_ids": self.target_accounts,
            "target_transaction_ids": self.target_transactions,
        }
        for key, items in mapping.items():
            if items:
                out[key] = items
        out.update(self.scalars)
        return out


# ====================================================================== #
# shared execution context
# ====================================================================== #
@dataclass
class AIContext:
    config: AIConfig
    providers: ProviderManager
    registry: ToolRegistry
    client: GraphClient
    prompts: PromptLibrary
    audit: AuditLog
    cache: ToolResultCache
    emitters: dict[str, Callable[[dict[str, Any]], None]] = field(default_factory=dict)

    def emit(self, investigation_id: str, event: dict[str, Any]) -> None:
        sink = self.emitters.get(investigation_id)
        if sink is None:
            return
        try:
            sink({"investigation_id": investigation_id, "at": time.time(), **event})
        except Exception:  # noqa: BLE001 - progress events must not break runs
            logger.debug("event sink failed", exc_info=True)


# ====================================================================== #
# LLM access
# ====================================================================== #
class LLMClient:
    def __init__(self, ctx: AIContext) -> None:
        self.ctx = ctx

    async def call(
        self,
        state: InvestigationState,
        fx: Effects,
        *,
        system: str,
        user: str,
        tools: list[Any] | None = None,
        json_response: bool = False,
        stage: str = "unknown",
    ) -> ProviderResponse:
        request = ProviderRequest(
            messages=[
                ProviderMessage(role="system", content=system),
                ProviderMessage(role="user", content=user),
            ],
            tools=list(tools or []),
            temperature=self.ctx.config.temperature,
            max_tokens=self.ctx.config.max_tokens,
            json_response=json_response,
            metadata={"stage": stage, "investigation_id": state.get("investigation_id", "")},
        )
        result = await self.ctx.providers.complete(request)
        for switch in result.switches:
            fx.fallback_history.append(switch.to_dict())
        if result.provider not in fx.providers_used:
            fx.providers_used.append(result.provider)
        fx.scalars["provider_used"] = result.provider
        self.ctx.audit.record(
            "llm_call",
            state.get("investigation_id", ""),
            stage=stage,
            provider=result.provider,
            fallback=result.used_fallback,
            tool_calls=len(result.response.tool_calls),
            input_tokens=result.response.usage.input_tokens,
            output_tokens=result.response.usage.output_tokens,
            latency_ms=round(result.response.latency_ms, 2),
        )
        self.ctx.emit(
            state.get("investigation_id", ""),
            {
                "type": "llm_call",
                "stage": stage,
                "provider": result.provider,
                "fallback": result.used_fallback,
            },
        )
        return result.response

    async def json(
        self,
        state: InvestigationState,
        fx: Effects,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        stage: str,
        tools: list[Any] | None = None,
    ) -> tuple[Any | None, str | None]:
        """One bounded repair attempt on malformed/invalid JSON."""
        attempt_user = user
        last_error: str | None = None
        for attempt in range(1 + max(0, self.ctx.config.max_llm_repairs) + 1):
            response = await self.call(
                state,
                fx,
                system=system,
                user=attempt_user,
                tools=tools,
                json_response=True,
                stage=stage,
            )
            data = parse_json_block(response.text)
            if data is None:
                last_error = "model returned non-JSON output"
                attempt_user = _repair_message(last_error, response.text or "")
                continue
            try:
                return schema.model_validate(data), None
            except ValidationError as exc:
                last_error = _format_validation(exc)
                attempt_user = _repair_message(last_error, response.text or "")
                continue
        return None, last_error


# ====================================================================== #
# deterministic helpers
# ====================================================================== #
def detect_use_case(state: InvestigationState) -> str:
    explicit = state.get("use_case") or "auto"
    if explicit and explicit != "auto":
        return explicit
    query = (state.get("investigator_query") or "").lower()
    accounts = state.get("target_account_ids") or []
    if any(k in query for k in ("cycle", "circular", "round trip", "back to")):
        return "circular"
    if any(k in query for k in ("pass-through", "pass through", "rapid", "within seconds")):
        return "pass_through"
    if any(k in query for k in ("multi-hop", "multi hop", "trace", "path", "flow to", "follow the money")):
        return "multi_hop"
    if any(k in query for k in ("compare", "together", "coordinat", "shared", "these accounts")) and len(accounts) >= 2:
        return "collective"
    if any(k in query for k in ("mule", "aggregat", "collect and distribute", "fan-in", "fan in")):
        return "money_mule"
    if not accounts and not (state.get("target_transaction_ids") or []):
        return "question"
    return "collective" if len(accounts) >= 2 else "money_mule"


def _targets_from_query(query: str, client: GraphClient, limit: int) -> tuple[list[str], list[str]]:
    accounts: list[str] = []
    transactions: list[str] = []
    if not query:
        return accounts, transactions
    for token in _ACCOUNT_TOKEN.findall(query):
        if len(accounts) + len(transactions) >= limit:
            break
        if token in accounts or token in transactions:
            continue
        try:
            if client.account_exists(token):
                accounts.append(token)
                continue
        except Exception:  # noqa: BLE001 - target resolution is best effort
            pass
        if token.upper().startswith("TX"):
            try:
                details = client.transaction_details(token)
            except Exception:  # noqa: BLE001
                continue
            if details:
                transactions.append(token)
    return accounts, transactions


def default_plan(use_case: str, targets: list[str], window: str) -> InvestigationPlan:
    """Deterministic fallback plan (used when the model plan is invalid)."""
    anchor = targets[0] if targets else "<account>"
    catalog: dict[str, list[tuple[str, str]]] = {
        "money_mule": [
            ("get_account_profile", "Establish baseline activity for the target"),
            ("detect_fan_in", "Check aggregation from many senders"),
            ("detect_fan_out", "Check distribution to many receivers"),
            ("get_account_neighborhood", "Identify connected accounts"),
            ("get_graph_evidence", "Collect the full evidence bundle for the target"),
            ("get_connected_communities", "Check suspicious community concentration"),
        ],
        "multi_hop": [
            ("get_account_profile", "Baseline for the source account"),
            ("get_account_neighborhood", "Discover candidate destinations/intermediaries"),
            ("trace_money_flow", "Trace bounded multi-hop paths to a discovered counterparty"),
            ("analyze_temporal_patterns", "Check for rapid sequential transfers"),
        ],
        "collective": [
            ("compare_accounts", "Deterministic comparison of the investigated accounts"),
            ("get_connected_communities", "Check shared community membership"),
            ("get_account_profile", "Per-account baseline"),
        ],
        "circular": [
            ("detect_cycles", "Retrieve detected cycles, optionally scoped to the target"),
            ("get_account_profile", "Baseline for the target"),
            ("analyze_temporal_patterns", "Check repetition/timing of circular flows"),
        ],
        "pass_through": [
            ("analyze_temporal_patterns", "Measure incoming-to-outgoing timing"),
            ("detect_fan_in", "Count senders"),
            ("detect_fan_out", "Count receivers"),
            ("get_transaction_history", "Inspect sequential transfers"),
        ],
        "question": [
            ("get_account_profile", "Answer from account facts"),
            ("get_graph_evidence", "Collect evidence bundle"),
        ],
    }
    steps = catalog.get(use_case, catalog["money_mule"])
    return InvestigationPlan(
        objective=f"Investigate {anchor} for suspicious activity ({use_case})",
        time_window=None,
        hypotheses=[f"Test whether {anchor} shows {use_case}-style suspicious behaviour"],
        steps=[
            {
                "step": i + 1,
                "objective": why,
                "planned_tool": tool,
                "rationale": "deterministic fallback plan",
                "success_criteria": "evidence collected or tool reports no data",
            }
            for i, (tool, why) in enumerate(steps)
        ],
        stop_criteria=["budget exhausted", "all hypotheses decided", "no new evidence"],
        notes=["deterministic fallback plan (model plan unavailable)"],
    )


# ====================================================================== #
# node implementations
# ====================================================================== #
class InvestigationNodes:
    def __init__(self, ctx: AIContext) -> None:
        self.ctx = ctx
        self.llm = LLMClient(ctx)

    # ------------------------------------------------------------------ #
    # A. intake
    # ------------------------------------------------------------------ #
    async def intake(self, state: InvestigationState) -> dict[str, Any]:
        fx = Effects()
        cfg = self.ctx.config
        inv_id = state["investigation_id"]
        window = state.get("time_window") or cfg.default_time_window
        query = state.get("investigator_query") or ""

        accounts = list(state.get("target_account_ids") or [])[: cfg.max_targets]
        transactions = list(state.get("target_transaction_ids") or [])[: cfg.max_targets]
        if not accounts and not transactions and query:
            found_accounts, found_txs = _targets_from_query(query, self.ctx.client, cfg.max_targets)
            accounts = found_accounts
            transactions = found_txs
            if found_accounts or found_txs:
                fx.note(f"targets resolved from investigator query: {accounts + transactions}")

        # resume support: never duplicate targets or restart intake evidence
        known_accounts = set(state.get("target_account_ids", []))
        known_txs = set(state.get("target_transaction_ids", []))
        fx.target_accounts = [a for a in accounts if a not in known_accounts]
        fx.target_transactions = [t for t in transactions if t not in known_txs]

        if state.get("initial_graph_evidence"):
            fx.note("intake evidence already present; resuming investigation without restart")
            fx.scalars["updated_at"] = time.time()
            self.ctx.emit(inv_id, {"type": "phase", "phase": "resume"})
            return fx.delta()

        objective = state.get("investigation_objective") or ""
        if not objective:
            if query:
                objective = f"Answer investigator question: {query}"
            elif accounts:
                objective = (
                    f"Autonomously investigate account(s) {', '.join(accounts)} for "
                    f"suspicious transaction behaviour"
                )
            elif transactions:
                objective = f"Investigate transaction(s) {', '.join(transactions)} and related accounts"
            else:
                objective = "Summarise current graph risk posture (no specific target supplied)"
        fx.scalars["investigation_objective"] = objective

        use_case = detect_use_case({**state, **fx.delta()})
        fx.scalars["use_case"] = use_case if state.get("use_case") in (None, "", "auto") else state["use_case"]
        fx.scalars["time_window"] = window
        fx.scalars["execution_status"] = "running"
        fx.scalars["updated_at"] = time.time()

        # deterministic initial evidence (no model involvement)
        evidence_specs: list[tuple[str, dict[str, Any]]] = []
        for i, account in enumerate(accounts[:3]):
            if i == 0:
                evidence_specs.append(
                    ("get_graph_evidence", {"account_id": account, "window": window, "profile": "FAST"})
                )
            else:
                evidence_specs.append(("get_account_profile", {"account_id": account, "window": window}))
        for tx in transactions[:3]:
            evidence_specs.append(("get_transaction_details", {"transaction_id": tx}))

        for tool_name, arguments in evidence_specs:
            result = await self._run_tool(state, fx, tool_name, arguments)
            fx.initial_evidence.append(
                {
                    "source_tool": tool_name,
                    "target": arguments.get("account_id") or arguments.get("transaction_id"),
                    "ok": result.ok,
                    "summary": self._fact_for(result),
                    "error": result.error,
                }
            )

        try:
            stats = await asyncio.to_thread(self.ctx.client.stats)
            fx.initial_evidence.append(
                {
                    "source_tool": "graph_stats",
                    "target": None,
                    "ok": True,
                    "summary": (
                        f"Graph scope: {stats.get('nodes')} accounts, {stats.get('edges')} "
                        f"edges, {stats.get('transactions')} transactions, graph_version "
                        f"{stats.get('graph_version')}."
                    ),
                    "error": None,
                }
            )
        except Exception as exc:  # noqa: BLE001 - stats are informational
            fx.note(f"graph stats unavailable: {type(exc).__name__}")

        self.ctx.audit.record("intake", inv_id, accounts=accounts, transactions=transactions, use_case=use_case)
        self.ctx.emit(inv_id, {"type": "phase", "phase": "intake", "use_case": use_case})
        return fx.delta()

    # ------------------------------------------------------------------ #
    # B. planning
    # ------------------------------------------------------------------ #
    async def plan(self, state: InvestigationState) -> dict[str, Any]:
        fx = Effects()
        inv_id = state["investigation_id"]
        if (state.get("investigation_plan") or {}).get("steps"):
            fx.scalars["updated_at"] = time.time()
            return fx.delta()
        window = state.get("time_window") or self.ctx.config.default_time_window
        use_case = state.get("use_case") or "money_mule"
        targets = list(state.get("target_account_ids") or [])

        initial = [
            {"tool": e.get("source_tool"), "target": e.get("target"), "summary": e.get("summary")}
            for e in state.get("initial_graph_evidence", [])
        ]
        user_payload = {
            "objective": state.get("investigation_objective"),
            "investigator_query": state.get("investigator_query"),
            "use_case": use_case,
            "time_window": window,
            "target_accounts": targets,
            "target_transactions": state.get("target_transaction_ids", []),
            "initial_evidence": initial,
            "available_tools": self.ctx.registry.describe(),
            "budget": {
                "max_tool_calls": state.get("max_tool_calls_budget", self.ctx.config.max_tool_calls),
                "max_steps": state.get("max_steps_budget", self.ctx.config.max_steps),
                "max_tools_per_step": self.ctx.config.max_tools_per_step,
            },
        }
        plan: InvestigationPlan | None = None
        error: str | None = None
        plan, error = await self.llm.json(
            state,
            fx,
            system=self.ctx.prompts.stage("planning"),
            user=json.dumps(user_payload, default=str, indent=1),
            schema=InvestigationPlan,
            stage="plan",
        )

        if plan is None:
            plan = default_plan(use_case, targets, window)
            fx.note(f"model plan invalid ({error}); used deterministic fallback plan")
            self.ctx.audit.record("validation", inv_id, stage="plan", error=error)

        # only registry tools may be planned
        cleaned_steps = []
        for step in plan.steps:
            if step.planned_tool in self.ctx.registry:
                cleaned_steps.append(step)
            else:
                fx.note(f"plan referenced unknown tool {step.planned_tool!r}; dropped")
        if not cleaned_steps:
            cleaned_steps = default_plan(use_case, targets, window).steps
        plan.steps = cleaned_steps
        if not plan.time_window:
            plan.time_window = None  # type: ignore[assignment]

        fx.scalars["investigation_plan"] = plan.model_dump()
        fx.scalars["updated_at"] = time.time()
        fx.scalars["investigation_steps"] = state.get("investigation_steps", 0) + 1
        self.ctx.audit.record("plan", inv_id, steps=len(plan.steps), hypotheses=len(plan.hypotheses))
        self.ctx.emit(inv_id, {"type": "phase", "phase": "plan", "steps": len(plan.steps)})
        return fx.delta()

    # ------------------------------------------------------------------ #
    # C. autonomous tool execution
    # ------------------------------------------------------------------ #
    async def act(self, state: InvestigationState) -> dict[str, Any]:
        fx = Effects()
        inv_id = state["investigation_id"]
        remaining = self._remaining_tool_calls(state)
        if remaining <= 0:
            fx.scalars["budget_exhausted"] = True
            fx.scalars["updated_at"] = time.time()
            return fx.delta()

        tool_calls, decision, reasoning, error = await self._select_tools(state, fx)
        if error:
            fx.note(f"tool selection failed: {error}")

        budget = self.ctx.config.max_tools_per_step
        selected = tool_calls[: min(budget, remaining)]
        if decision == "sufficient" and not selected:
            fx.scalars["last_decision"] = "sufficient"
            fx.scalars["updated_at"] = time.time()
            fx.scalars["investigation_steps"] = state.get("investigation_steps", 0) + 1
            return fx.delta()

        evidence_before = len(state.get("evidence_collection", [])) + len(fx.evidence)
        for call in selected:
            name = call.get("name") if isinstance(call, dict) else None
            arguments = call.get("arguments") if isinstance(call, dict) else None
            if not name:
                fx.note("model produced a tool call without a name; skipped")
                continue
            if name not in self.ctx.registry:
                fx.note(f"model requested unknown tool {name!r}; skipped")
                continue
            if arguments is not None and not isinstance(arguments, dict):
                fx.note(f"tool {name} arguments must be an object; skipped")
                continue
            await self._run_tool(state, fx, name, arguments or {})

        executed = len(selected)
        evidence_after = len(state.get("evidence_collection", [])) + len(fx.evidence)
        new_ok = evidence_after - evidence_before
        stall = state.get("steps_without_new_evidence", 0)
        stall = 0 if new_ok > 0 else stall + 1

        tool_count = state.get("tool_call_count", 0) + executed
        steps = state.get("investigation_steps", 0) + 1
        budget_hit = (
            tool_count >= state.get("max_tool_calls_budget", self.ctx.config.max_tool_calls)
            or steps >= state.get("max_steps_budget", self.ctx.config.max_steps)
            or time.time() >= state.get("deadline_at", time.time() + 1)
        )

        fx.scalars.update(
            {
                "tool_call_count": tool_count,
                "investigation_steps": steps,
                "steps_without_new_evidence": stall,
                "last_decision": decision or ("continue" if selected else "continue"),
                "budget_exhausted": bool(state.get("budget_exhausted")) or budget_hit,
                "updated_at": time.time(),
                "execution_status": "running",
            }
        )
        if reasoning:
            self.ctx.emit(inv_id, {"type": "reasoning", "stage": "act", "text": reasoning[:300]})
        self.ctx.emit(
            inv_id,
            {
                "type": "step",
                "step": steps,
                "tools": [c.get("name") for c in selected if isinstance(c, dict)],
                "decision": decision,
                "tool_call_count": tool_count,
            },
        )
        return fx.delta()

    def route_after_act(self, state: InvestigationState) -> str:
        if state.get("budget_exhausted"):
            return "conclude"
        if time.time() >= state.get("deadline_at", 0):
            return "conclude"
        if state.get("last_decision") == "sufficient":
            return "correlate"
        if state.get("steps_without_new_evidence", 0) >= self.ctx.config.max_stall_steps:
            return "correlate"
        if state.get("tool_call_count", 0) >= state.get(
            "max_tool_calls_budget", self.ctx.config.max_tool_calls
        ):
            return "conclude"
        if state.get("investigation_steps", 0) >= state.get(
            "max_steps_budget", self.ctx.config.max_steps
        ):
            return "conclude"
        return "act"

    # ------------------------------------------------------------------ #
    # D. evidence correlation
    # ------------------------------------------------------------------ #
    async def correlate(self, state: InvestigationState) -> dict[str, Any]:
        fx = Effects()
        inv_id = state["investigation_id"]
        context = {
            "objective": state.get("investigation_objective"),
            "use_case": state.get("use_case"),
            "evidence": self._evidence_digest(state),
            "tool_history": summarize_payload(
                state.get("tool_execution_history", []), self.ctx.config.history_char_budget
            )[0],
            "known_references": sorted(self._known_references(state))[:200],
        }
        output: CorrelationOutput | None = None
        error: str | None = None
        output, error = await self.llm.json(
            state,
            fx,
            system=self.ctx.prompts.stage("correlation"),
            user=json.dumps(context, default=str, indent=1),
            schema=CorrelationOutput,
            stage="correlate",
        )
        if output is None:
            fx.note(f"model correlation invalid ({error}); used deterministic correlation")
            self.ctx.audit.record("validation", inv_id, stage="correlate", error=error)
            output = self._deterministic_correlation(state)

        known = self._known_references(state)
        for pattern in output.discovered_patterns:
            pattern.evidence_refs = [r for r in pattern.evidence_refs if r in known] or [
                r for r in pattern.transaction_ids if r in known
            ][:5]
            dropped = [
                r
                for r in (pattern.accounts + pattern.transaction_ids)
                if r not in known
            ]
            if dropped:
                fx.note(f"dropped unverified references from pattern {pattern.pattern_type}: {dropped[:5]}")
            pattern.accounts = [a for a in pattern.accounts if a in known]
            pattern.transaction_ids = [t for t in pattern.transaction_ids if t in known]
            fx.discovered_patterns.append(pattern.model_dump())

        for item in output.contradictions:
            item.evidence_refs = [r for r in item.evidence_refs if r in known]
            fx.contradictions.append(item.model_dump())
        for item in output.alternative_explanations:
            item.evidence_refs = [r for r in item.evidence_refs if r in known]
            fx.alternatives.append(item.model_dump())
        for item in output.missing_evidence:
            fx.missing.append(item.model_dump())
        fx.scalars["_correlation_notes"] = [str(n) for n in output.correlation_notes[:10]]

        fx.scalars["updated_at"] = time.time()
        fx.scalars["investigation_steps"] = state.get("investigation_steps", 0) + 1
        self.ctx.audit.record(
            "correlate",
            inv_id,
            patterns=len(fx.discovered_patterns),
            contradictions=len(fx.contradictions),
            alternatives=len(fx.alternatives),
            missing=len(fx.missing),
        )
        self.ctx.emit(inv_id, {"type": "phase", "phase": "correlate"})
        return fx.delta()

    # ------------------------------------------------------------------ #
    # E. conclusion (deterministic)
    # ------------------------------------------------------------------ #
    async def conclude(self, state: InvestigationState) -> dict[str, Any]:
        fx = Effects()
        inv_id = state["investigation_id"]
        evidence = state.get("evidence_collection", [])
        ok_records = [e for e in evidence if e.get("ok")]

        # --- observed facts (never model-generated) ----------------------
        facts = [
            {
                "statement": record.get("summary", ""),
                "evidence_refs": [record.get("evidence_id", "")] + list(
                    record.get("transaction_ids", [])
                )[:5],
                "source": record.get("tool", "graph_engine"),
            }
            for record in ok_records[:60]
            if record.get("summary")
        ]

        # --- patterns / paths / transactions extracted from evidence ------
        patterns: list[dict[str, Any]] = []
        tx_evidence: list[dict[str, Any]] = []
        paths: list[dict[str, Any]] = []
        for record in ok_records:
            data = record.get("data") or {}
            patterns.extend(_extract_patterns(data, record))
            tx_evidence.extend(_extract_transactions(data))
            if record.get("tool") == "trace_money_flow":
                paths.extend(_extract_paths(data))
        # include model-correlated patterns as well (already validated refs)
        known_pattern_keys = {
            (p.get("pattern_type"), tuple(p.get("transaction_ids", [])[:3]))
            for p in state.get("discovered_patterns", [])
        }
        merged_patterns = list(state.get("discovered_patterns", []))
        for pattern in patterns:
            key = (pattern.get("pattern_type"), tuple(pattern.get("transaction_ids", [])[:3]))
            if key not in known_pattern_keys:
                merged_patterns.append(pattern)
                known_pattern_keys.add(key)

        # --- involved accounts (deterministic union) ----------------------
        role_map: dict[str, str] = {}
        for account in state.get("target_account_ids", []):
            role_map[account] = "investigation target"
        for path in paths:
            accounts = path.get("accounts") or []
            if accounts:
                role_map.setdefault(accounts[0], "money-flow source")
                role_map.setdefault(accounts[-1], "money-flow destination")
                for mid in accounts[1:-1]:
                    role_map.setdefault(mid, "intermediary")
        for record in ok_records:
            for account in record.get("account_ids", [])[:50]:
                role_map.setdefault(account, "counterparty")
        for pattern in merged_patterns:
            for account in pattern.get("accounts", []):
                role_map.setdefault(account, "pattern participant")
        involved = [
            {
                "account_id": account_id,
                "role": role,
                "observed_behaviour": "",
                "risk_indicators": [],
            }
            for account_id, role in list(role_map.items())[:60]
        ]

        # --- evidence strength (rule-based, basis recorded) ---------------
        strength, basis = _evidence_strength(state, ok_records, merged_patterns)

        # --- deterministic limitations ------------------------------------
        limitations: list[str] = []
        switches = state.get("fallback_history", [])
        for switch in switches:
            if switch.get("reason") != "unknown":
                limitations.append(
                    f"Provider {switch.get('provider')} unavailable during the investigation "
                    f"({switch.get('reason')}): {switch.get('message', '')[:160]}"
                )
        if state.get("budget_exhausted"):
            limitations.append(
                "Investigation stopped at a configured autonomy budget "
                f"(tool calls {state.get('tool_call_count')}, steps {state.get('investigation_steps')})."
            )
        if state.get("steps_without_new_evidence", 0) >= self.ctx.config.max_stall_steps:
            limitations.append("Stopped early: additional tool calls were yielding no new evidence.")
        if any(r.get("truncated") for r in ok_records):
            limitations.append("Some tool outputs were truncated to fit the model context budget.")
        limitations.append(
            "Evidence comes only from the transaction graph; no KYC, device or "
            "external watchlist data was available."
        )
        limitations.append(
            "Multi-hop results are structural paths, not provenance of specific funds."
        )
        limitations.append(
            "All recommendations require human review; no automated account action was taken."
        )

        # --- default alternatives / missing evidence when the model gave none
        alternatives = list(state.get("alternative_explanations", []))
        if not alternatives:
            alternatives = _default_alternatives(merged_patterns)
        missing = list(state.get("missing_evidence", []))
        if not missing:
            missing = [
                {
                    "missing": "External identity / KYC data for involved accounts",
                    "why_it_matters": "Graph structure alone cannot distinguish a mule from an active merchant or payroll aggregator.",
                    "how_to_obtain": "Pull KYC and onboarding records from the core banking system.",
                },
                {
                    "missing": "Transaction narrative / UPI purpose fields",
                    "why_it_matters": "Purpose text can corroborate or refute layering hypotheses.",
                    "how_to_obtain": "Request payment purpose metadata for the cited transaction ids.",
                },
            ]

        # --- recommended next steps (deterministic base) -------------------
        base_steps = [
            {
                "action": "Human analyst reviews the cited transaction ids and connected accounts",
                "rationale": "Every conclusion in this report must be verified against source records before action.",
                "priority": "high",
                "requires_human_review": True,
            },
            {
                "action": "Extend the investigation time window and re-run the pattern checks",
                "rationale": "Short windows can hide or overstate patterns; repetition across windows is a strong signal.",
                "priority": "medium",
                "requires_human_review": True,
            },
        ]
        if state.get("budget_exhausted"):
            base_steps.append(
                {
                    "action": "Re-run with a larger autonomy budget for full coverage",
                    "rationale": "The investigation stopped before all planned steps completed.",
                    "priority": "medium",
                    "requires_human_review": True,
                }
            )

        metrics = {
            "tool_calls": state.get("tool_call_count", 0),
            "successful_tool_calls": len(ok_records),
            "failed_tool_calls": len(evidence) - len(ok_records),
            "distinct_tools_used": sorted({e.get("tool", "") for e in evidence}),
            "evidence_items": len(evidence),
            "accounts_investigated": sorted(set(state.get("investigated_accounts", []))),
            "patterns_found": len(merged_patterns),
            "paths_found": len(paths),
            "transactions_referenced": len({t.get("transaction_id") for t in tx_evidence}),
            "contradictions": len(state.get("contradictions", [])),
            "graph_version": ok_records[-1].get("graph_version") if ok_records else None,
            "wall_clock_seconds": round(time.time() - state.get("started_at", time.time()), 2),
            "providers_used": sorted(
                set(state.get("providers_used", []))
                | ({state.get("provider_used")} if state.get("provider_used") else set())
            ),
            "cache_stats": self.ctx.cache.stats(),
        }

        fx.scalars.update(
            {
                "_observed_facts": facts,
                "_detected_patterns": merged_patterns,
                "_transaction_evidence": tx_evidence[:150],
                "_money_flow_paths": paths[:25],
                "_involved_accounts": involved,
                "_evidence_strength": strength,
                "_evidence_strength_basis": basis,
                "_limitations": limitations,
                "_alternatives": alternatives,
                "_missing": missing,
                "_base_next_steps": base_steps,
                "_supporting_metrics": metrics,
                "updated_at": time.time(),
                "investigation_steps": state.get("investigation_steps", 0) + 1,
            }
        )
        self.ctx.audit.record(
            "conclude",
            inv_id,
            facts=len(facts),
            patterns=len(merged_patterns),
            evidence_strength=strength,
        )
        self.ctx.emit(inv_id, {"type": "phase", "phase": "conclude", "evidence_strength": strength})
        return fx.delta()

    # ------------------------------------------------------------------ #
    # F. report generation
    # ------------------------------------------------------------------ #
    async def report(self, state: InvestigationState) -> dict[str, Any]:
        fx = Effects()
        inv_id = state["investigation_id"]
        facts = state.get("_observed_facts", []) or []
        narrative_input = {
            "objective": state.get("investigation_objective"),
            "investigator_query": state.get("investigator_query"),
            "observed_facts": [f.get("statement") for f in facts],
            "detected_patterns": state.get("_detected_patterns", []),
            "contradictions": state.get("contradictions", []),
            "alternative_explanations": state.get("_alternatives", []),
            "missing_evidence": state.get("_missing", []),
            "supporting_metrics": state.get("_supporting_metrics", {}),
            "evidence_strength": state.get("_evidence_strength", "insufficient"),
            "evidence_strength_basis": state.get("_evidence_strength_basis", ""),
            "known_account_ids": [a.get("account_id") for a in state.get("_involved_accounts", [])],
        }
        narrative: ReportNarrative | None = None
        error: str | None = None
        narrative, error = await self.llm.json(
            state,
            fx,
            system=self.ctx.prompts.stage("report"),
            user=json.dumps(narrative_input, default=str, indent=1),
            schema=ReportNarrative,
            stage="report",
        )
        if narrative is None:
            fx.note(f"model narrative invalid ({error}); used deterministic narrative")
            self.ctx.audit.record("validation", inv_id, stage="report", error=error)
            narrative = _deterministic_narrative(state, facts)

        # merge narrative into the strict report skeleton
        known_accounts = {
            a.get("account_id") for a in state.get("_involved_accounts", []) if a.get("account_id")
        }
        account_enrichment = {
            a.account_id: a for a in narrative.involved_accounts if a.account_id in known_accounts
        }
        unknown = [a.account_id for a in narrative.involved_accounts if a.account_id not in known_accounts]
        if unknown:
            fx.note(f"report introduced unknown account ids (dropped): {unknown[:5]}")

        involved = []
        for base in state.get("_involved_accounts", []):
            enrich = account_enrichment.get(base.get("account_id"))
            if enrich is not None:
                involved.append(enrich.model_dump())
            else:
                involved.append(base)

        provider = state.get("provider_used") or (
            state["providers_used"][-1] if state.get("providers_used") else "unknown"
        )
        stalled = state.get("steps_without_new_evidence", 0) >= self.ctx.config.max_stall_steps
        status = "completed"
        if state.get("budget_exhausted"):
            if state.get("tool_call_count", 0) >= state.get(
                "max_tool_calls_budget", self.ctx.config.max_tool_calls
            ):
                status = "limit_reached"
            else:
                status = "completed_partial"
        elif stalled:
            status = "completed_partial"

        report_payload: dict[str, Any] = {
            "investigation_id": inv_id,
            "target_accounts": state.get("target_account_ids", []),
            "target_transaction_ids": state.get("target_transaction_ids", []),
            "provider_used": provider,
            "investigation_status": status,
            "executive_summary": narrative.executive_summary,
            "observed_facts": facts,
            "detected_patterns": state.get("_detected_patterns", []),
            "involved_accounts": involved,
            "transaction_evidence": state.get("_transaction_evidence", []),
            "money_flow_paths": state.get("_money_flow_paths", []),
            "supporting_metrics": state.get("_supporting_metrics", {}),
            "reasoning": [r.model_dump() for r in narrative.reasoning],
            "alternative_explanations": state.get("_alternatives", []),
            "contradictory_evidence": state.get("contradictions", []),
            "missing_evidence": state.get("_missing", []),
            "evidence_strength": state.get("_evidence_strength", "insufficient"),
            "evidence_strength_basis": state.get("_evidence_strength_basis", ""),
            "recommended_next_steps": [
                s.model_dump() for s in narrative.recommended_next_steps
            ]
            + state.get("_base_next_steps", []),
            "limitations": _dedupe(
                state.get("_limitations", []) + list(narrative.limitations)
            ),
            "investigation_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "provider_switches": state.get("fallback_history", []),
            "validation_notes": state.get("validation_notes", []),
        }

        try:
            report = InvestigationReport.model_validate(report_payload)
        except ValidationError as exc:
            fx.note(f"merged report invalid ({_format_validation(exc)}); repairing")
            repaired = _repair_report_payload(report_payload, exc)
            try:
                report = InvestigationReport.model_validate(repaired)
            except ValidationError:
                # last resort: deterministic, evidence-only report (no invention)
                fx.note("report repair failed; emitted deterministic evidence-only report")
                report = InvestigationReport.model_validate(
                    _deterministic_report_payload(state, facts, provider, status)
                )

        fx.scalars["final_report"] = report.model_dump()
        fx.scalars["execution_status"] = status
        fx.scalars["updated_at"] = time.time()
        self.ctx.audit.record(
            "report",
            inv_id,
            status=status,
            evidence_strength=report.evidence_strength,
            facts=len(report.observed_facts),
            patterns=len(report.detected_patterns),
        )
        self.ctx.emit(
            inv_id,
            {
                "type": "report",
                "status": status,
                "evidence_strength": report.evidence_strength,
                "investigation_id": inv_id,
            },
        )
        return fx.delta()

    # ------------------------------------------------------------------ #
    # shared tool execution
    # ------------------------------------------------------------------ #
    async def _run_tool(
        self,
        state: InvestigationState,
        fx: Effects,
        name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        cfg = self.ctx.config
        inv_id = state.get("investigation_id", "")
        graph_version: int | None = None
        try:
            graph_version = await asyncio.to_thread(self.ctx.client.graph_version)
        except Exception:  # noqa: BLE001 - version is best effort
            graph_version = None

        cached_data = None
        if graph_version is not None and cfg.cache_enabled:
            cached_data = self.ctx.cache.get(name, arguments, graph_version)

        if cached_data is not None:
            result = ToolResult(
                tool=name,
                arguments=dict(arguments),
                ok=True,
                data=cached_data,
                graph_version=graph_version,
                cached=True,
                provenance="mulegraph.graph_engine(cache)",
            )
        else:
            result = await asyncio.to_thread(
                lambda: self.ctx.registry.invoke(
                    name, arguments, self.ctx.client, cfg.tool_result_char_budget
                )
            )
            if result.ok and result.graph_version is not None and cfg.cache_enabled:
                self.ctx.cache.put(name, arguments, result.graph_version, result.data)

        fx.tool_history.append(result.to_history())
        if result.ok:
            seq = len(state.get("evidence_collection", [])) + len(fx.evidence)
            record = _evidence_record(result, self.ctx.registry, seq)
            fx.evidence.append(record)
            for account in (arguments.get("account_id"), arguments.get("source_account")):
                if account and account not in fx.investigated:
                    fx.investigated.append(account)
            if name == "trace_money_flow" and isinstance(result.data, dict):
                fx.paths.extend(_extract_paths(result.data))
        self.ctx.audit.record(
            "tool_call",
            inv_id,
            tool=name,
            arguments={k: v for k, v in (arguments or {}).items()},
            ok=result.ok,
            error_kind=result.error_kind,
            error=result.error,
            duration_ms=round(result.duration_ms, 2),
            cached=result.cached,
            graph_version=result.graph_version,
        )
        self.ctx.emit(
            inv_id,
            {
                "type": "tool_result",
                "tool": name,
                "ok": result.ok,
                "error": result.error,
                "cached": result.cached,
                "duration_ms": round(result.duration_ms, 2),
            },
        )
        return result

    def _fact_for(self, result: ToolResult) -> str:
        if not result.ok:
            return f"{result.tool} failed: {result.error}"
        spec = self.ctx.registry.get(result.tool)
        if spec and spec.fact_builder and isinstance(result.data, dict):
            try:
                return spec.fact_builder(result.data, result.arguments)
            except Exception:  # noqa: BLE001 - fact text is best effort
                return f"{result.tool} returned {len(result.data)} fields"
        return f"{result.tool} returned data"

    def _remaining_tool_calls(self, state: InvestigationState) -> int:
        cap = state.get("max_tool_calls_budget", self.ctx.config.max_tool_calls)
        return max(0, cap - state.get("tool_call_count", 0))

    # ------------------------------------------------------------------ #
    async def _select_tools(
        self, state: InvestigationState, fx: Effects
    ) -> tuple[list[dict[str, Any]], str, str, str | None]:
        inv_id = state["investigation_id"]
        plan = state.get("investigation_plan") or {}
        planned = plan.get("steps", [])
        history = state.get("tool_execution_history", [])
        executed_tools = {h.get("tool") for h in history if h.get("ok")}
        uncovered = [s for s in planned if s.get("planned_tool") not in executed_tools]

        context = {
            "objective": state.get("investigation_objective"),
            "use_case": state.get("use_case"),
            "time_window": state.get("time_window"),
            "budget_remaining": self._remaining_tool_calls(state),
            "max_tools_this_step": self.ctx.config.max_tools_per_step,
            "plan_uncovered_steps": uncovered[:10],
            "evidence_so_far": self._evidence_digest(state),
            "already_executed_tools": sorted(executed_tools),
            "investigated_accounts": sorted(set(state.get("investigated_accounts", []))),
            "known_references": sorted(self._known_references(state))[:120],
        }
        user = json.dumps(context, default=str, indent=1)
        system = self.ctx.prompts.stage(
            "tool_selection", MAX_TOOLS_PER_STEP=self.ctx.config.max_tools_per_step
        )
        tools = self.ctx.registry.definitions()

        last_error: str | None = None
        attempt_user = user
        for _ in range(1 + max(0, self.ctx.config.max_llm_repairs) + 1):
            response = await self.llm.call(
                state, fx, system=system, user=attempt_user, tools=tools, stage="act"
            )
            if response.tool_calls:
                calls = [{"name": c.name, "arguments": c.arguments} for c in response.tool_calls]
                return calls, "continue", response.text[:300], None
            data = parse_json_block(response.text)
            if data is None:
                last_error = "model returned neither tool calls nor JSON"
                attempt_user = _repair_message(last_error, response.text or "")
                continue
            decision = str(data.get("decision", "continue")).lower()
            calls = data.get("tool_calls") or []
            if not isinstance(calls, list):
                last_error = "tool_calls must be a list"
                attempt_user = _repair_message(last_error, response.text or "")
                continue
            if decision not in ("continue", "sufficient"):
                last_error = "decision must be 'continue' or 'sufficient'"
                attempt_user = _repair_message(last_error, response.text or "")
                continue
            return calls, decision, str(data.get("reasoning", ""))[:300], None
        return [], "continue", "", last_error

    # ------------------------------------------------------------------ #
    def _evidence_digest(self, state: InvestigationState) -> list[dict[str, Any]]:
        digest: list[dict[str, Any]] = []
        for record in state.get("evidence_collection", [])[:40]:
            digest.append(
                {
                    "evidence_id": record.get("evidence_id"),
                    "tool": record.get("tool"),
                    "arguments": record.get("arguments"),
                    "summary": record.get("summary"),
                    "transaction_ids": (record.get("transaction_ids") or [])[:8],
                }
            )
        for extra in state.get("initial_graph_evidence", [])[:10]:
            digest.append(
                {
                    "source_tool": extra.get("source_tool"),
                    "target": extra.get("target"),
                    "summary": extra.get("summary"),
                }
            )
        trimmed, _ = summarize_payload(digest, self.ctx.config.evidence_context_char_budget)
        return trimmed if isinstance(trimmed, list) else digest[:20]

    @staticmethod
    def _known_references(state: InvestigationState) -> set[str]:
        known: set[str] = set()
        for history in state.get("tool_execution_history", []):
            known.add(str(history.get("tool", "")))
            for value in (history.get("arguments") or {}).values():
                if isinstance(value, str):
                    known.add(value)
        for record in state.get("evidence_collection", []):
            known.add(str(record.get("evidence_id", "")))
            known.update(str(x) for x in record.get("transaction_ids", []))
            known.update(str(x) for x in record.get("account_ids", []))
        for extra in state.get("initial_graph_evidence", []):
            if extra.get("target"):
                known.add(str(extra["target"]))
        known.update(state.get("target_account_ids", []))
        known.update(state.get("target_transaction_ids", []))
        known.update(state.get("investigated_accounts", []))
        known.discard("")
        return known

    def _deterministic_correlation(self, state: InvestigationState) -> "CorrelationOutput":
        """Fallback correlation derived only from collected evidence."""
        patterns: list[CorrelationPattern] = []
        for record in state.get("evidence_collection", []):
            if not record.get("ok"):
                continue
            data = record.get("data") or {}
            for pattern in _extract_patterns(data, record):
                patterns.append(
                    CorrelationPattern(
                        pattern_type=pattern["pattern_type"],
                        summary=pattern["summary"],
                        evidence_refs=[record.get("evidence_id", record.get("tool", ""))],
                        accounts=pattern.get("accounts", []),
                        transaction_ids=pattern.get("transaction_ids", []),
                    )
                )
        contradictions: list[Contradiction] = []
        missing: list[MissingEvidence] = [
            MissingEvidence(
                missing="Model-generated cross-tool correlation unavailable",
                why_it_matters="Correlations were derived deterministically from single-tool results only.",
                how_to_obtain="Re-run correlation when the model provider is healthy.",
            )
        ]
        return CorrelationOutput(
            discovered_patterns=patterns[:20],
            contradictions=contradictions,
            alternative_explanations=_default_alternatives(
                [p.model_dump() for p in patterns]
            ),
            missing_evidence=missing,
            correlation_notes=["deterministic correlation fallback used"],
        )


# ====================================================================== #
# output schemas for LLM stages
# ====================================================================== #
class CorrelationOutput(BaseModel):
    discovered_patterns: list[CorrelationPattern] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    alternative_explanations: list[AlternativeExplanation] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)
    correlation_notes: list[str] = Field(default_factory=list)

    @field_validator("correlation_notes", mode="before")
    @classmethod
    def _notes(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return [str(x) for x in v][:20]


class ReportNarrative(BaseModel):
    executive_summary: str = ""
    reasoning: list[ReasoningStep] = Field(default_factory=list)
    recommended_next_steps: list[RecommendedStep] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    involved_accounts: list[InvolvedAccount] = Field(default_factory=list)

    @field_validator("executive_summary", mode="before")
    @classmethod
    def _summary(cls, v: Any) -> str:
        return "" if v is None else str(v).strip()

    @field_validator("limitations", mode="before")
    @classmethod
    def _lims(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return [str(x) for x in v][:20]


# ====================================================================== #
# deterministic extractors (facts come from the engine, not the model)
# ====================================================================== #
def _extract_patterns(data: dict[str, Any], record: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    evidence_id = record.get("evidence_id", record.get("tool", ""))

    for pattern in data.get("detected_patterns") or []:
        if not isinstance(pattern, dict):
            continue
        out.append(
            {
                "pattern_type": str(pattern.get("pattern_type", "PATTERN")),
                "summary": str(pattern.get("explanation", ""))[:500],
                "evidence_refs": [evidence_id],
                "accounts": [str(a) for a in pattern.get("accounts_involved", [])][:30],
                "transaction_ids": [str(t) for t in pattern.get("transaction_ids", [])][:80],
            }
        )

    if "detected" in data and "direction" in data:
        if data.get("detected"):
            out.append(
                {
                    "pattern_type": f"FAN_{data.get('direction', 'IN')}",
                    "summary": (
                        f"{data.get('unique_accounts')} unique counterparties, "
                        f"{data.get('transaction_count')} transactions, total "
                        f"{data.get('total_amount')} (severity {data.get('severity')})"
                    ),
                    "evidence_refs": [evidence_id],
                    "accounts": [str(a) for a in data.get("counterparty_accounts", [])][:30]
                    + [str(data.get("account_id", ""))],
                    "transaction_ids": [str(t) for t in data.get("transaction_ids", [])][:80],
                }
            )

    for cycle in (data.get("cycles") or [])[:8]:
        if not isinstance(cycle, dict):
            continue
        out.append(
            {
                "pattern_type": "CIRCULAR_TRANSACTION",
                "summary": (
                    f"cycle of {cycle.get('length', len(cycle.get('accounts', [])))} accounts, "
                    f"total {cycle.get('total_amount')}, duration {cycle.get('duration_seconds')}s"
                ),
                "evidence_refs": [evidence_id],
                "accounts": [str(a) for a in cycle.get("accounts", [])][:20],
                "transaction_ids": [str(t) for t in cycle.get("transaction_ids", [])][:40],
            }
        )

    for motif in (data.get("motifs") or [])[:8]:
        if not isinstance(motif, dict):
            continue
        out.append(
            {
                "pattern_type": str(motif.get("pattern_type", motif.get("motif_type", "TEMPORAL_MOTIF"))),
                "summary": str(motif.get("explanation", ""))[:500],
                "evidence_refs": [evidence_id],
                "accounts": [str(a) for a in motif.get("accounts_involved", [])][:20],
                "transaction_ids": [str(t) for t in motif.get("transaction_ids", [])][:40],
            }
        )

    for community in data.get("account_communities") or []:
        if isinstance(community, dict) and community.get("suspicious_concentration"):
            out.append(
                {
                    "pattern_type": "COMMUNITY_CONCENTRATION",
                    "summary": (
                        f"{community.get('community_id')} size {community.get('size')} with "
                        f"suspicious volume concentration (connectivity "
                        f"{community.get('connectivity')})"
                    ),
                    "evidence_refs": [evidence_id],
                    "accounts": [str(a) for a in community.get("members", [])][:30],
                    "transaction_ids": [],
                }
            )
    return out


def _extract_transactions(data: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def take(rows: Any) -> None:
        if not isinstance(rows, list):
            return
        for row in rows[:120]:
            if not isinstance(row, dict) or "transaction_id" not in row:
                continue
            if "amount" not in row and "created_at" not in row and "timestamp" not in row:
                continue
            out.append(
                {
                    "transaction_id": str(row.get("transaction_id")),
                    "source_account": str(
                        row.get("source_account") or row.get("source") or row.get("from_account") or ""
                    ),
                    "destination_account": str(
                        row.get("destination_account")
                        or row.get("destination")
                        or row.get("to_account")
                        or ""
                    ),
                    "amount": row.get("amount"),
                    "timestamp": row.get("created_at", row.get("timestamp")),
                    "status": str(row.get("status", "")),
                    "relevance": "",
                }
            )

    take(data.get("edges"))
    take(data.get("transactions"))
    for path in data.get("paths") or []:
        if isinstance(path, dict):
            take(path.get("hops"))
    for cycle in data.get("cycles") or []:
        if not isinstance(cycle, dict):
            continue
        tx_ids = cycle.get("transaction_ids") or []
        amounts = cycle.get("amounts") or []
        stamps = cycle.get("timestamps") or []
        accounts = cycle.get("accounts") or []
        for i, tx_id in enumerate(tx_ids):
            src = accounts[i % len(accounts)] if accounts else ""
            dst = accounts[(i + 1) % len(accounts)] if accounts else ""
            out.append(
                {
                    "transaction_id": str(tx_id),
                    "source_account": str(src),
                    "destination_account": str(dst),
                    "amount": amounts[i] if i < len(amounts) else None,
                    "timestamp": stamps[i] if i < len(stamps) else None,
                    "status": "",
                    "relevance": "cycle member",
                }
            )

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in out:
        if item["transaction_id"] in seen:
            continue
        seen.add(item["transaction_id"])
        deduped.append(item)
    return deduped


def _extract_paths(data: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in data.get("paths") or []:
        if not isinstance(path, dict):
            continue
        out.append(
            {
                "source": str(path.get("source", "")),
                "destination": str(path.get("destination", "")),
                "hop_count": int(path.get("hop_count", len(path.get("hops", [])))),
                "accounts": [str(a) for a in path.get("accounts", [])][:20],
                "transaction_ids": [str(t) for t in path.get("transaction_ids", [])][:40],
                "total_amount": path.get("total_amount"),
                "note": "structural path only; not provenance of specific funds",
            }
        )
    return out


def _evidence_strength(
    state: InvestigationState,
    ok_records: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
) -> tuple[str, str]:
    if not ok_records:
        return (
            "insufficient",
            "No successful graph tool result was collected.",
        )
    tools_used = {r.get("tool") for r in ok_records}
    tx_refs = {t for r in ok_records for t in (r.get("transaction_ids") or [])}
    contradictions = state.get("contradictions", [])
    budget_hit = state.get("budget_exhausted", False)

    basis_parts = [
        f"{len(ok_records)} successful tool result(s)",
        f"{len(tools_used)} distinct tool(s): {', '.join(sorted(t for t in tools_used if t))}",
        f"{len(patterns)} detected pattern(s)",
        f"{len(tx_refs)} distinct transaction reference(s)",
        f"{len(contradictions)} contradiction(s)",
    ]
    if budget_hit:
        basis_parts.append("autonomy budget reached before full coverage")
    basis = "; ".join(basis_parts) + "."

    if len(patterns) == 0:
        strength = "low" if (len(ok_records) >= 2 and not contradictions) else "insufficient"
        if len(ok_records) < 2:
            strength = "insufficient"
    elif contradictions and len(contradictions) >= 2:
        strength = "moderate"
    elif len(patterns) >= 2 and len(tools_used) >= 4 and len(tx_refs) >= 5 and not budget_hit:
        strength = "strong"
    else:
        strength = "moderate"
    return strength, basis


def _default_alternatives(patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    types = {str(p.get("pattern_type", "")).upper() for p in patterns}
    out: list[dict[str, Any]] = []
    if any("FAN_IN" in t for t in types):
        out.append(
            {
                "explanation": "Many-to-one transfers can be a payroll run, a merchant aggregating customer payments, or a family pooling funds.",
                "plausibility": "moderate",
                "evidence_refs": [],
            }
        )
    if any("FAN_OUT" in t for t in types):
        out.append(
            {
                "explanation": "One-to-many transfers can be salary/contractor payouts or marketplace seller settlements.",
                "plausibility": "moderate",
                "evidence_refs": [],
            }
        )
    if any("CIRCULAR" in t or "CYCLE" in t for t in types):
        out.append(
            {
                "explanation": "Cycles can arise from refunds, reversals, or repeated bill payments between the same parties.",
                "plausibility": "moderate",
                "evidence_refs": [],
            }
        )
    if any("TEMPORAL" in t or "PASS" in t for t in types):
        out.append(
            {
                "explanation": "Rapid in-out timing is also typical of wallet top-ups followed by an immediate purchase.",
                "plausibility": "moderate",
                "evidence_refs": [],
            }
        )
    if not out:
        out.append(
            {
                "explanation": "Normal high-velocity customer activity can look similar to suspicious flow without external context.",
                "plausibility": "moderate",
                "evidence_refs": [],
            }
        )
    return out


def _deterministic_narrative(
    state: InvestigationState, facts: list[dict[str, Any]]
) -> ReportNarrative:
    strength = state.get("_evidence_strength", "insufficient")
    objective = state.get("investigation_objective", "the requested investigation")
    summary_lines = [
        f"Investigation of: {objective}.",
        f"Evidence strength: {strength} ({state.get('_evidence_strength_basis', '')})",
    ]
    if facts:
        summary_lines.append("Key observed facts:")
        summary_lines.extend(f"- {f.get('statement')}" for f in facts[:5])
    else:
        summary_lines.append("No graph evidence was successfully collected.")
    return ReportNarrative(
        executive_summary=" ".join(summary_lines),
        reasoning=[
            {"claim": f.get("statement", ""), "kind": "fact", "evidence_refs": f.get("evidence_refs", [])}
            for f in facts[:8]
        ],
        recommended_next_steps=[],
        limitations=["Deterministic narrative used because the model narrative was invalid."],
        involved_accounts=[],
    )


def _repair_report_payload(payload: dict[str, Any], exc: ValidationError) -> dict[str, Any]:
    """Bounded, non-inventive repair: drop offending items, keep the rest."""
    fixed = dict(payload)
    list_fields = {
        "observed_facts",
        "detected_patterns",
        "involved_accounts",
        "transaction_evidence",
        "money_flow_paths",
        "reasoning",
        "alternative_explanations",
        "contradictory_evidence",
        "missing_evidence",
        "recommended_next_steps",
        "limitations",
        "target_accounts",
        "target_transaction_ids",
        "validation_notes",
        "provider_switches",
    }
    for err in exc.errors():
        loc = err.get("loc", ())
        if not loc:
            continue
        target: Any = fixed
        for key in loc[:-1]:
            if isinstance(target, list) and isinstance(key, int) and key < len(target):
                target = target[key]
            elif isinstance(target, dict) and key in target:
                target = target[key]
            else:
                target = None
                break
        if not isinstance(target, dict):
            continue
        leaf = loc[-1]
        if leaf in list_fields or leaf in fixed and isinstance(fixed.get(leaf), list):
            if leaf in fixed and isinstance(fixed.get(leaf), list):
                fixed[leaf] = []
            elif leaf in target and isinstance(target.get(leaf), list):
                target[leaf] = []
        elif leaf in target:
            target[leaf] = ""
    for key in ("limitations", "validation_notes"):
        if isinstance(fixed.get(key), str):
            fixed[key] = [fixed[key]] if fixed[key] else []
    if not fixed.get("executive_summary"):
        fixed["executive_summary"] = (
            "Report generated with validation issues; see limitations."
        )
    return fixed


def _deterministic_report_payload(
    state: InvestigationState,
    facts: list[dict[str, Any]],
    provider: str,
    status: str,
) -> dict[str, Any]:
    return {
        "investigation_id": state.get("investigation_id", "unknown"),
        "target_accounts": state.get("target_account_ids", []),
        "target_transaction_ids": state.get("target_transaction_ids", []),
        "provider_used": provider,
        "investigation_status": status,
        "executive_summary": (
            "Evidence-only report generated without model narrative. "
            + (facts[0].get("statement", "") if facts else "No graph evidence collected.")
        ),
        "observed_facts": facts,
        "detected_patterns": state.get("_detected_patterns", []),
        "involved_accounts": state.get("_involved_accounts", []),
        "transaction_evidence": state.get("_transaction_evidence", []),
        "money_flow_paths": state.get("_money_flow_paths", []),
        "supporting_metrics": state.get("_supporting_metrics", {}),
        "reasoning": [
            {"claim": f.get("statement", ""), "kind": "fact", "evidence_refs": f.get("evidence_refs", [])}
            for f in facts[:10]
        ],
        "alternative_explanations": state.get("_alternatives", []),
        "contradictory_evidence": state.get("contradictions", []),
        "missing_evidence": state.get("_missing", []),
        "evidence_strength": state.get("_evidence_strength", "insufficient"),
        "evidence_strength_basis": state.get("_evidence_strength_basis", ""),
        "recommended_next_steps": state.get("_base_next_steps", []),
        "limitations": state.get("_limitations", []),
        "investigation_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "provider_switches": state.get("fallback_history", []),
        "validation_notes": state.get("validation_notes", []),
    }


def _evidence_record(
    result: ToolResult, registry: ToolRegistry, seq: int | None
) -> dict[str, Any]:
    spec = registry.get(result.tool)
    fact = ""
    if spec and spec.fact_builder and isinstance(result.data, dict):
        try:
            fact = spec.fact_builder(result.data, result.arguments)
        except Exception:  # noqa: BLE001
            fact = ""
    index = seq if seq is not None else int(time.time() * 1000) % 1_000_000
    return {
        "evidence_id": f"EV-{result.tool}-{index:03d}",
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


def _dedupe(items: list[Any]) -> list[str]:
    seen: list[str] = []
    for item in items:
        text = str(item)
        if text and text not in seen:
            seen.append(text)
    return seen


__all__ = [
    "AIContext",
    "CorrelationOutput",
    "Effects",
    "InvestigationNodes",
    "LLMClient",
    "ReportNarrative",
    "default_plan",
    "detect_use_case",
    "parse_json_block",
]
