"""Pydantic request/response schemas for the graph API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ..graph.models import TransactionEvent

ProfileName = Literal["FAST", "STANDARD", "DEEP"]
WindowName = Literal["5s", "30s", "5m", "1h", "24h"]


# --------------------------------------------------------------------- #
# requests
# --------------------------------------------------------------------- #
class AnalyzeRequest(BaseModel):
    """POST /api/v1/graph/analyze"""

    account_id: str = Field(..., min_length=1, description="Account to analyse")
    time_window: WindowName = Field(default="5m", description="Sliding window preset")
    profile: ProfileName = Field(default="STANDARD", description="Analysis profile")
    include_subgraph: bool = Field(default=False, description="Include extracted subgraph")
    connected_limit: int = Field(default=25, ge=1, le=200, description="Max connected accounts returned")

    @field_validator("account_id")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("account_id must not be empty")
        return v


class TransactionIngestRequest(BaseModel):
    """POST /api/v1/graph/transaction - accepts a single event or a batch."""

    events: list[TransactionEvent] = Field(default_factory=list, description="Batch of events")
    event: TransactionEvent | None = Field(default=None, description="Single event")

    @field_validator("events")
    @classmethod
    def _limit_batch(cls, v: list[TransactionEvent]) -> list[TransactionEvent]:
        if len(v) > 1000:
            raise ValueError("batch limited to 1000 events per request")
        return v

    def all_events(self) -> list[TransactionEvent]:
        if self.event is not None:
            return [self.event, *self.events]
        return list(self.events)


# --------------------------------------------------------------------- #
# responses
# --------------------------------------------------------------------- #
class IngestEventResult(BaseModel):
    event_id: str
    transaction_id: str
    accepted: bool
    action: str
    graph_version: int
    detail: str = ""


class IngestResponse(BaseModel):
    status: Literal["accepted", "partial", "empty"]
    processed: int
    accepted: int
    duplicates: int
    results: list[IngestEventResult]
    graph_version: int


class AccountSummaryResponse(BaseModel):
    account_id: str
    exists: bool
    window: WindowName | None = None
    first_seen: float | None = None
    last_seen: float | None = None
    degrees: dict[str, int] = Field(default_factory=dict)
    activity: dict[str, Any] = Field(default_factory=dict)
    transaction_count: int = 0
    settled_amount: float = 0.0
    graph_version: int


class NeighborhoodResponse(BaseModel):
    account_id: str
    hops: int
    time_window: WindowName
    node_count: int
    edge_count: int
    truncated: bool
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class PatternsResponse(BaseModel):
    account_id: str
    time_window: WindowName
    profile: str
    pattern_count: int
    patterns: list[dict[str, Any]]
    risk_assessment: dict[str, Any]
    analysis_id: str
    analysis_metadata: dict[str, Any]
    page: int = 1
    page_size: int = 50
    total_pages: int = 1


class TraceResponse(BaseModel):
    source: str
    destination: str
    time_window: WindowName | None
    path_count: int
    shortest_hops: int | None
    truncated: bool
    paths: list[dict[str, Any]]
    detection_parameters: dict[str, Any]


class CyclesResponse(BaseModel):
    time_window: WindowName
    cycle_count: int
    cycles: list[dict[str, Any]]
    repeated_activity: list[dict[str, Any]]
    detection_parameters: dict[str, Any]


class CommunitiesResponse(BaseModel):
    time_window: WindowName
    community_count: int
    algorithm: str
    communities: list[dict[str, Any]]
    page: int = 1
    page_size: int = 50
    total_pages: int = 1


class MetricsResponse(BaseModel):
    time_window: WindowName
    account_id: str | None = None
    accounts_measured: int
    bridge_nodes: list[str]
    top_pagerank: list[dict[str, Any]]
    top_betweenness: list[dict[str, Any]]
    metrics: dict[str, Any]
    parameters: dict[str, Any]


class HealthResponse(BaseModel):
    status: str
    graph_version: int
    nodes: int
    edges: int
    cache_status: dict[str, Any]


class StatsResponse(BaseModel):
    status: str = "ok"
    store: dict[str, Any]
    windows: list[str]
    profiles: list[str]
    uptime_seconds: float
    events_processed: int
    analyses_run: int


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: Any = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class AnalyzeResponse(BaseModel):
    """The AI-ready structured graph intelligence output (section 8)."""

    analysis_id: str
    analysis_status: str
    target_account: str | None
    target_transaction: str | None
    time_window: str
    profile: str
    graph_summary: dict[str, Any]
    detected_patterns: list[dict[str, Any]]
    money_flow_paths: list[dict[str, Any]]
    communities: list[dict[str, Any]]
    centrality_metrics: dict[str, Any]
    connected_accounts: list[dict[str, Any]]
    graph_evidence: list[dict[str, Any]]
    risk_assessment: dict[str, Any]
    analysis_metadata: dict[str, Any]
    subgraph: dict[str, Any] | None = None

    model_config = {"extra": "allow"}
