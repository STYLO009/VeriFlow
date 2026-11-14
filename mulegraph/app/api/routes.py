"""FastAPI routes for the MuleGraph graph intelligence engine.

All endpoints are synchronous (FastAPI runs them in its threadpool) so the
graph engine stays independent of async frameworks internally.
"""

from __future__ import annotations

import math
import time
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from ..algorithms.centrality import compute_centrality
from ..algorithms.cycle_detection import find_cycles
from ..algorithms.multi_hop import trace_money_flow
from ..config import WINDOW_PRESETS
from ..graph.adjacency_index import Window
from ..graph.models import GraphDomainError, LimitExceededError
from .schemas import (
    AccountSummaryResponse,
    AnalyzeRequest,
    AnalyzeResponse,
    CyclesResponse,
    CommunitiesResponse,
    ErrorBody,
    ErrorResponse,
    HealthResponse,
    IngestEventResult,
    IngestResponse,
    MetricsResponse,
    NeighborhoodResponse,
    PatternsResponse,
    StatsResponse,
    TraceResponse,
    TransactionIngestRequest,
)

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])


def get_services(request: Request) -> dict[str, Any]:
    """Dependency: shared application services assembled in ``main.py``."""
    return request.app.state.services


def _paginate(items: list[Any], page: int, page_size: int) -> tuple[list[Any], int]:
    total_pages = max(1, math.ceil(len(items) / page_size))
    start = (page - 1) * page_size
    return items[start : start + page_size], total_pages


# --------------------------------------------------------------------- #
# analysis
# --------------------------------------------------------------------- #
@router.post("/analyze", response_model=AnalyzeResponse, summary="Run graph intelligence analysis")
def analyze(request: AnalyzeRequest, services: dict[str, Any] = Depends(get_services)) -> AnalyzeResponse:
    services["counters"]["analyses"] += 1
    result = services["analyzer"].analyze_account(
        request.account_id,
        window=request.time_window,
        profile=request.profile,
        include_subgraph=request.include_subgraph,
        connected_limit=request.connected_limit,
    )
    return AnalyzeResponse.model_validate(result.to_dict())


@router.post("/transaction", response_model=IngestResponse, summary="Ingest transaction event(s)")
def ingest(payload: TransactionIngestRequest, services: dict[str, Any] = Depends(get_services)) -> IngestResponse:
    events = payload.all_events()
    if not events:
        raise GraphDomainError("no events supplied: provide 'event' or 'events'")

    builder = services["builder"]
    repository = services["repository"]
    processor = services["processor"]

    results: list[IngestEventResult] = []
    accepted = 0
    duplicates = 0
    for event in events:
        result = builder.build(event)
        if result.accepted:
            repository.append(event)
        if result.action == "duplicate":
            duplicates += 1
        if result.accepted:
            accepted += 1
        # streaming-compatible fast analysis after every accepted event
        if processor is not None and result.accepted:
            processor.on_event(event)
        results.append(
            IngestEventResult(
                event_id=result.event_id,
                transaction_id=result.transaction_id,
                accepted=result.accepted,
                action=result.action,
                graph_version=result.graph_version,
                detail=result.detail,
            )
        )

    status = "accepted" if accepted == len(events) else ("partial" if accepted else "empty")
    return IngestResponse(
        status=status,
        processed=len(events),
        accepted=accepted,
        duplicates=duplicates,
        results=results,
        graph_version=services["store"].version,
    )


# --------------------------------------------------------------------- #
# account views
# --------------------------------------------------------------------- #
@router.get("/account/{account_id}", response_model=AccountSummaryResponse, summary="Account summary")
def account(
    account_id: str,
    window: str = Query("5m", description="Window preset"),
    services: dict[str, Any] = Depends(get_services),
) -> AccountSummaryResponse:
    store = services["store"]
    resolved = Window.preset(window)
    exists = store.has_account(account_id)
    data = store.graph.nodes.get(account_id, {})
    records = store.transactions_for_account(account_id, resolved) if exists else []
    settled = [r for r in records if r.is_settled]
    return AccountSummaryResponse(
        account_id=account_id,
        exists=exists,
        window=window,  # type: ignore[arg-type]
        first_seen=data.get("first_seen"),
        last_seen=data.get("last_seen"),
        degrees=store.degrees(account_id, resolved) if exists else {},
        activity=services["temporal"].account_activity(account_id, resolved) if exists else {},
        transaction_count=len(records),
        settled_amount=round(sum(r.amount for r in settled), 2),
        graph_version=store.version,
    )


@router.get(
    "/account/{account_id}/neighborhood",
    response_model=NeighborhoodResponse,
    summary="Bounded neighbourhood extraction",
)
def neighborhood(
    account_id: str,
    hops: int = Query(1, ge=1, le=4, description="BFS depth"),
    window: str = Query("5m", description="Window preset"),
    services: dict[str, Any] = Depends(get_services),
) -> NeighborhoodResponse:
    from ..intelligence.subgraph_extractor import extract_subgraph

    store = services["store"]
    if not store.has_account(account_id):
        raise LookupError(f"account {account_id} not found")
    view = extract_subgraph(store, account_id, hops=hops, window=Window.preset(window))
    payload = view.to_dict()
    return NeighborhoodResponse(
        account_id=account_id,
        hops=hops,
        time_window=window,  # type: ignore[arg-type]
        node_count=payload["node_count"],
        edge_count=payload["edge_count"],
        truncated=payload["truncated"],
        nodes=payload["nodes"],
        edges=payload["edges"],
    )


@router.get(
    "/account/{account_id}/patterns",
    response_model=PatternsResponse,
    summary="Detected patterns for an account (paginated)",
)
def patterns(
    account_id: str,
    window: str = Query("5m"),
    profile: str = Query("STANDARD", pattern="^(FAST|STANDARD|DEEP)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    services: dict[str, Any] = Depends(get_services),
) -> PatternsResponse:
    services["counters"]["analyses"] += 1
    result = services["analyzer"].analyze_account(account_id, window=window, profile=profile)
    page_items, total_pages = _paginate(result.detected_patterns, page, page_size)
    return PatternsResponse(
        account_id=account_id,
        time_window=window,  # type: ignore[arg-type]
        profile=profile,
        pattern_count=len(result.detected_patterns),
        patterns=page_items,
        risk_assessment=result.risk_assessment,
        analysis_id=result.analysis_id,
        analysis_metadata=result.analysis_metadata,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/account/{account_id}/transactions",
    response_model=AccountSummaryResponse,
    summary="Account transaction summary (paginated amounts in activity)",
)
def account_transactions(
    account_id: str,
    window: str = Query("5m"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    services: dict[str, Any] = Depends(get_services),
) -> AccountSummaryResponse:
    store = services["store"]
    resolved = Window.preset(window)
    if not store.has_account(account_id):
        raise LookupError(f"account {account_id} not found")
    records = store.transactions_for_account(account_id, resolved)
    page_items, _ = _paginate(records, page, page_size)
    settled = [r for r in records if r.is_settled]
    return AccountSummaryResponse(
        account_id=account_id,
        exists=True,
        window=window,  # type: ignore[arg-type]
        first_seen=store.graph.nodes[account_id].get("first_seen"),
        last_seen=store.graph.nodes[account_id].get("last_seen"),
        degrees=store.degrees(account_id, resolved),
        activity={
            "page": page,
            "page_size": page_size,
            "total_transactions": len(records),
            "transactions": [r.to_dict() for r in page_items],
        },
        transaction_count=len(records),
        settled_amount=round(sum(r.amount for r in settled), 2),
        graph_version=store.version,
    )


# --------------------------------------------------------------------- #
# graph-wide analysis endpoints
# --------------------------------------------------------------------- #
@router.get("/trace/{source_id}/{destination_id}", response_model=TraceResponse, summary="Trace money flow")
def trace(
    source_id: str,
    destination_id: str,
    max_hops: int = Query(4, ge=1, le=6),
    window: str | None = Query("24h"),
    min_amount: float | None = Query(None, gt=0),
    shortest_only: bool = Query(False),
    chronological: bool = Query(False, description="Require non-decreasing timestamps"),
    services: dict[str, Any] = Depends(get_services),
) -> TraceResponse:
    resolved = Window.preset(window) if window else None
    result = trace_money_flow(
        services["store"],
        source_id,
        destination_id,
        max_hops=max_hops,
        window=resolved,
        min_amount=min_amount,
        shortest_only=shortest_only,
        strict_chronological=chronological,
    )
    payload = result.to_dict()
    return TraceResponse(
        source=source_id,
        destination=destination_id,
        time_window=window,  # type: ignore[arg-type]
        path_count=payload["path_count"],
        shortest_hops=payload["shortest_hops"],
        truncated=payload["truncated"],
        paths=payload["paths"],
        detection_parameters=payload["detection_parameters"],
    )


@router.get("/cycles", response_model=CyclesResponse, summary="Detect circular transactions")
def cycles(
    window: str = Query("24h"),
    min_length: int = Query(3, ge=2, le=8),
    max_length: int | None = Query(None, ge=3, le=8),
    services: dict[str, Any] = Depends(get_services),
) -> CyclesResponse:
    result = find_cycles(
        services["store"],
        window=Window.preset(window),
        min_length=min_length,
        max_length=max_length,
    )
    payload = result.to_dict()
    return CyclesResponse(
        time_window=window,  # type: ignore[arg-type]
        cycle_count=payload["cycle_count"],
        cycles=payload["cycles"],
        repeated_activity=payload["repeated_activity"],
        detection_parameters=payload["detection_parameters"],
    )


@router.get("/communities", response_model=CommunitiesResponse, summary="Community detection")
def communities(
    window: str = Query("24h"),
    min_size: int = Query(3, ge=2, le=50),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    services: dict[str, Any] = Depends(get_services),
) -> CommunitiesResponse:
    analyzer = services["analyzer"]
    resolved = Window.preset(window)
    scan = analyzer._communities_for(resolved)  # cached + background refreshed
    items, total_pages = _paginate([c.to_dict() for c in scan.communities], page, page_size)
    filtered = [c for c in items if c["size"] >= min_size]
    return CommunitiesResponse(
        time_window=window,  # type: ignore[arg-type]
        community_count=len(scan.communities),
        algorithm=scan.algorithm,
        communities=filtered,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/metrics", response_model=MetricsResponse, summary="Centrality metrics")
def metrics(
    account_id: str | None = Query(None, description="Optionally scope to one account"),
    window: str = Query("24h"),
    services: dict[str, Any] = Depends(get_services),
) -> MetricsResponse:
    analyzer = services["analyzer"]
    resolved = Window.preset(window)
    scan = analyzer._centrality_for(resolved)  # cached + background refreshed
    payload = scan.to_dict(include_all=account_id is None)
    scoped = {account_id: scan.for_account(account_id)} if account_id else payload["metrics"]
    return MetricsResponse(
        time_window=window,  # type: ignore[arg-type]
        account_id=account_id,
        accounts_measured=len(scan.metrics),
        bridge_nodes=scan.bridge_nodes,
        top_pagerank=scan.top_pagerank,
        top_betweenness=scan.top_betweenness,
        metrics=scoped or {},
        parameters=scan.parameters,
    )


# --------------------------------------------------------------------- #
# operational
# --------------------------------------------------------------------- #
@router.get("/health", response_model=HealthResponse, summary="Graph engine health")
def health(services: dict[str, Any] = Depends(get_services)) -> HealthResponse:
    payload = services["analyzer"].health()
    return HealthResponse(**payload)


@router.get("/stats", response_model=StatsResponse, summary="Graph engine statistics")
def stats(services: dict[str, Any] = Depends(get_services)) -> StatsResponse:
    store = services["store"]
    counters = services["counters"]
    return StatsResponse(
        store=store.stats(),
        windows=list(WINDOW_PRESETS),
        profiles=["FAST", "STANDARD", "DEEP"],
        uptime_seconds=round(time.time() - counters["started_at"], 2),
        events_processed=counters["events"],
        analyses_run=counters["analyses"],
    )


__all__ = [
    "router",
    "ErrorBody",
    "ErrorResponse",
    "LimitExceededError",
]
