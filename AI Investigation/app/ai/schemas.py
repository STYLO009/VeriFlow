"""Strict Pydantic schemas for the AI investigation layer.

Everything the model produces is validated here before it is returned to a
caller. Item validators deliberately accept a bare string and coerce it into
the canonical object shape ("bounded repair") so a slightly sloppy model
answer can be fixed without inventing any content.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .config import VALID_PROFILES, VALID_WINDOWS

WindowName = Literal["5s", "30s", "5m", "1h", "24h"]
ProfileName = Literal["FAST", "STANDARD", "DEEP"]
EvidenceStrength = Literal["low", "moderate", "strong", "insufficient"]
InvestigationStatus = Literal["completed", "completed_partial", "failed", "limit_reached"]

UseCase = Literal[
    "money_mule",
    "multi_hop",
    "collective",
    "circular",
    "pass_through",
    "question",
    "auto",
]

MAX_TEXT = 4000
MAX_LIST_ITEMS = 200


def _clean_text(value: Any, field_name: str) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    # strip control characters (keeps the payload single-line safe in logs)
    text = "".join(ch for ch in text if ch.isprintable() or ch in ("\n", "\t"))
    if len(text) > MAX_TEXT * 4:
        text = text[: MAX_TEXT * 4]
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ValueError("expected a list of strings")
    return [str(v) for v in value][:MAX_LIST_ITEMS]


# --------------------------------------------------------------------- #
# investigation plan (stage B)
# --------------------------------------------------------------------- #
class PlanStep(BaseModel):
    step: int = Field(default=1, ge=1, le=50)
    objective: str = Field(..., min_length=1)
    planned_tool: str = Field(..., min_length=1, description="Logical tool name from the registry")
    rationale: str = Field(default="")
    success_criteria: str = Field(default="")

    @field_validator("objective", "planned_tool", "rationale", "success_criteria", mode="before")
    @classmethod
    def _text(cls, v: Any) -> str:
        return "" if v is None else str(v).strip()


class InvestigationPlan(BaseModel):
    objective: str = Field(..., min_length=1)
    time_window: WindowName | None = None
    hypotheses: list[str] = Field(default_factory=list, max_length=20)
    steps: list[PlanStep] = Field(default_factory=list, max_length=30)
    stop_criteria: list[str] = Field(default_factory=list, max_length=20)
    notes: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("objective", mode="before")
    @classmethod
    def _objective(cls, v: Any) -> str:
        return _clean_text(v, "objective")

    @field_validator("hypotheses", "stop_criteria", "notes", mode="before")
    @classmethod
    def _texts(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        return [str(x).strip() for x in v if str(x).strip()][:20]


class CorrelationPattern(BaseModel):
    pattern_type: str = Field(..., min_length=1, description="e.g. FAN_IN, RAPID_PASS_THROUGH")
    summary: str = Field(..., min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    accounts: list[str] = Field(default_factory=list)
    transaction_ids: list[str] = Field(default_factory=list)

    @field_validator("pattern_type", mode="before")
    @classmethod
    def _pt(cls, v: Any) -> str:
        return _clean_text(v, "pattern_type")

    @field_validator("summary", mode="before")
    @classmethod
    def _sum(cls, v: Any) -> str:
        return _clean_text(v, "summary")

    @field_validator("evidence_refs", "accounts", "transaction_ids", mode="before")
    @classmethod
    def _refs(cls, v: Any) -> list[str]:
        return _string_list(v)


class Contradiction(BaseModel):
    observation: str = Field(..., min_length=1)
    weakens: str = Field(default="", description="Which suspicion / pattern this weakens")
    evidence_refs: list[str] = Field(default_factory=list)

    @field_validator("observation", "weakens", mode="before")
    @classmethod
    def _t(cls, v: Any) -> str:
        return "" if v is None else str(v).strip()

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def _r(cls, v: Any) -> list[str]:
        return _string_list(v)

    @model_validator(mode="before")
    @classmethod
    def _coerce_str(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"observation": data}
        return data


class AlternativeExplanation(BaseModel):
    explanation: str = Field(..., min_length=1)
    plausibility: Literal["low", "moderate", "high"] = "moderate"
    evidence_refs: list[str] = Field(default_factory=list)

    @field_validator("explanation", mode="before")
    @classmethod
    def _t(cls, v: Any) -> str:
        return _clean_text(v, "explanation")

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def _r(cls, v: Any) -> list[str]:
        return _string_list(v)

    @model_validator(mode="before")
    @classmethod
    def _coerce_str(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"explanation": data}
        return data


class MissingEvidence(BaseModel):
    missing: str = Field(..., min_length=1)
    why_it_matters: str = Field(default="")
    how_to_obtain: str = Field(default="")

    @field_validator("missing", "why_it_matters", "how_to_obtain", mode="before")
    @classmethod
    def _t(cls, v: Any) -> str:
        return _clean_text(v, "missing") if v is not None and str(v).strip() else ("" if v is None else str(v))

    @model_validator(mode="before")
    @classmethod
    def _coerce_str(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"missing": data}
        return data


# --------------------------------------------------------------------- #
# final report (section 8)
# --------------------------------------------------------------------- #
class ObservedFact(BaseModel):
    statement: str = Field(..., min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    source: str = Field(default="graph_engine")

    @field_validator("statement", mode="before")
    @classmethod
    def _s(cls, v: Any) -> str:
        return _clean_text(v, "statement")

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def _r(cls, v: Any) -> list[str]:
        return _string_list(v)

    @model_validator(mode="before")
    @classmethod
    def _coerce_str(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"statement": data}
        return data


class InvolvedAccount(BaseModel):
    account_id: str = Field(..., min_length=1)
    role: str = Field(default="counterparty")
    observed_behaviour: str = Field(default="")
    risk_indicators: list[str] = Field(default_factory=list)

    @field_validator("account_id", mode="before")
    @classmethod
    def _a(cls, v: Any) -> str:
        return _clean_text(v, "account_id")

    @field_validator("role", "observed_behaviour", mode="before")
    @classmethod
    def _t(cls, v: Any) -> str:
        return "" if v is None else str(v).strip()

    @field_validator("risk_indicators", mode="before")
    @classmethod
    def _i(cls, v: Any) -> list[str]:
        return _string_list(v)

    @model_validator(mode="before")
    @classmethod
    def _coerce_str(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"account_id": data}
        return data


class TransactionEvidence(BaseModel):
    transaction_id: str = Field(..., min_length=1)
    source_account: str = Field(default="")
    destination_account: str = Field(default="")
    amount: float | None = None
    timestamp: float | None = None
    status: str = Field(default="")
    relevance: str = Field(default="")

    @field_validator("transaction_id", mode="before")
    @classmethod
    def _t(cls, v: Any) -> str:
        return _clean_text(v, "transaction_id")

    @field_validator("source_account", "destination_account", "status", "relevance", mode="before")
    @classmethod
    def _s(cls, v: Any) -> str:
        return "" if v is None else str(v).strip()

    @model_validator(mode="before")
    @classmethod
    def _coerce_str(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"transaction_id": data}
        return data


class MoneyFlowPath(BaseModel):
    source: str = Field(default="")
    destination: str = Field(default="")
    hop_count: int = 0
    accounts: list[str] = Field(default_factory=list)
    transaction_ids: list[str] = Field(default_factory=list)
    total_amount: float | None = None
    note: str = Field(default="")

    @field_validator("source", "destination", "note", mode="before")
    @classmethod
    def _s(cls, v: Any) -> str:
        return "" if v is None else str(v).strip()

    @field_validator("accounts", "transaction_ids", mode="before")
    @classmethod
    def _l(cls, v: Any) -> list[str]:
        return _string_list(v)


class ReasoningStep(BaseModel):
    claim: str = Field(..., min_length=1)
    kind: Literal["fact", "interpretation"] = "interpretation"
    evidence_refs: list[str] = Field(default_factory=list)

    @field_validator("claim", mode="before")
    @classmethod
    def _c(cls, v: Any) -> str:
        return _clean_text(v, "claim")

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def _r(cls, v: Any) -> list[str]:
        return _string_list(v)

    @model_validator(mode="before")
    @classmethod
    def _coerce_str(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"claim": data}
        return data


class RecommendedStep(BaseModel):
    action: str = Field(..., min_length=1)
    rationale: str = Field(default="")
    priority: Literal["low", "medium", "high"] = "medium"
    requires_human_review: bool = True

    @field_validator("action", "rationale", mode="before")
    @classmethod
    def _t(cls, v: Any) -> str:
        return _clean_text(v, "action")

    @model_validator(mode="before")
    @classmethod
    def _coerce_str(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"action": data}
        return data


class InvestigationReport(BaseModel):
    """The final structured investigation response (section 8)."""

    investigation_id: str = Field(..., min_length=1)
    target_accounts: list[str] = Field(default_factory=list)
    provider_used: str = Field(..., min_length=1)
    investigation_status: InvestigationStatus = "completed"
    executive_summary: str = Field(default="")
    observed_facts: list[ObservedFact] = Field(default_factory=list)
    detected_patterns: list[CorrelationPattern] = Field(default_factory=list)
    involved_accounts: list[InvolvedAccount] = Field(default_factory=list)
    transaction_evidence: list[TransactionEvidence] = Field(default_factory=list)
    money_flow_paths: list[MoneyFlowPath] = Field(default_factory=list)
    supporting_metrics: dict[str, Any] = Field(default_factory=dict)
    reasoning: list[ReasoningStep] = Field(default_factory=list)
    alternative_explanations: list[AlternativeExplanation] = Field(default_factory=list)
    contradictory_evidence: list[Contradiction] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)
    evidence_strength: EvidenceStrength = "insufficient"
    evidence_strength_basis: str = Field(default="")
    recommended_next_steps: list[RecommendedStep] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    investigation_timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # extra, additive provenance fields (never required by clients)
    target_transaction_ids: list[str] = Field(default_factory=list)
    provider_switches: list[dict[str, Any]] = Field(default_factory=list)
    validation_notes: list[str] = Field(default_factory=list)

    @field_validator("target_accounts", "target_transaction_ids", mode="before")
    @classmethod
    def _ids(cls, v: Any) -> list[str]:
        return _string_list(v)

    @field_validator("executive_summary", mode="before")
    @classmethod
    def _summary(cls, v: Any) -> str:
        return "" if v is None else str(v).strip()

    @field_validator("limitations", mode="before")
    @classmethod
    def _lim(cls, v: Any) -> list[str]:
        return _string_list(v)

    @field_validator("provider_switches", "validation_notes", mode="before")
    @classmethod
    def _raw(cls, v: Any) -> list[Any]:
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        return v[:50]


# --------------------------------------------------------------------- #
# AI API request/response DTOs
# --------------------------------------------------------------------- #
class InvestigateRequest(BaseModel):
    account_ids: list[str] = Field(default_factory=list, max_length=10)
    transaction_ids: list[str] = Field(default_factory=list, max_length=10)
    question: str | None = Field(default=None, max_length=4000)
    use_case: UseCase = "auto"
    time_window: WindowName = Field(default="24h")
    profile: ProfileName = Field(default="FAST")
    max_tool_calls: int | None = Field(default=None, ge=1, le=200)
    max_steps: int | None = Field(default=None, ge=1, le=50)
    stream: bool = False

    @field_validator("question", mode="before")
    @classmethod
    def _q(cls, v: Any) -> str | None:
        if v is None:
            return None
        text = str(v).strip()
        return text or None


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    investigation_id: str | None = Field(default=None, max_length=64)
    session_id: str | None = Field(default=None, max_length=64)
    account_ids: list[str] = Field(default_factory=list, max_length=10)
    time_window: WindowName = Field(default="24h")

    @field_validator("message", mode="before")
    @classmethod
    def _m(cls, v: Any) -> str:
        return _clean_text(v, "message")


class ChatResponse(BaseModel):
    investigation_id: str
    answer: str
    evidence_refs: list[str] = Field(default_factory=list)
    provider_used: str
    tools_used: list[str] = Field(default_factory=list)
    investigation_status: InvestigationStatus
    created_new_investigation: bool = False


class InvestigationSummary(BaseModel):
    investigation_id: str
    status: str
    objective: str = ""
    use_case: str = ""
    target_accounts: list[str] = Field(default_factory=list)
    target_transaction_ids: list[str] = Field(default_factory=list)
    investigation_steps: int = 0
    tool_call_count: int = 0
    provider_used: str = ""
    providers_used: list[str] = Field(default_factory=list)
    fallback_history: list[dict[str, Any]] = Field(default_factory=list)
    execution_status: str = ""
    report_ready: bool = False
    started_at: float | None = None
    updated_at: float | None = None
    evidence_counts: dict[str, int] = Field(default_factory=dict)


class ProviderInfo(BaseModel):
    id: str
    role: str
    model: str
    configured: bool
    healthy: bool | None = None
    last_error: str | None = None
    last_error_kind: str | None = None
    requests: int = 0
    failures: int = 0
    fallback_switches_in: int = 0
    last_success_at: float | None = None
    mean_latency_ms: float | None = None


class ProviderStatusResponse(BaseModel):
    providers: list[ProviderInfo]
    active_order: list[str]
    any_configured: bool
    config: dict[str, Any] = Field(default_factory=dict)
    recent_switches: list[dict[str, Any]] = Field(default_factory=list)


class AIHealthResponse(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    providers_configured: bool
    providers_available: int
    graph_version: int | None = None
    graph_backend: str
    investigations_tracked: int
    detail: str = ""


class AIErrorBody(BaseModel):
    code: str
    message: str
    detail: Any = None


class AIErrorResponse(BaseModel):
    error: AIErrorBody


__all__ = [
    "AIErrorBody",
    "AIErrorResponse",
    "AIHealthResponse",
    "AlternativeExplanation",
    "ChatRequest",
    "ChatResponse",
    "Contradiction",
    "CorrelationPattern",
    "EvidenceStrength",
    "InvestigateRequest",
    "InvestigationPlan",
    "InvestigationReport",
    "InvestigationStatus",
    "InvestigationSummary",
    "InvolvedAccount",
    "MissingEvidence",
    "MoneyFlowPath",
    "ObservedFact",
    "PlanStep",
    "ProfileName",
    "ProviderInfo",
    "ProviderStatusResponse",
    "ReasoningStep",
    "RecommendedStep",
    "TransactionEvidence",
    "UseCase",
    "WindowName",
]
