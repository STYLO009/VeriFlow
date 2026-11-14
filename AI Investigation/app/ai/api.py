"""AI-only API endpoints (section 10).

    POST /api/v1/ai/investigate
    POST /api/v1/ai/chat
    GET  /api/v1/ai/investigation/{investigation_id}
    GET  /api/v1/ai/investigation/{investigation_id}/report
    GET  /api/v1/ai/providers/status
    GET  /api/v1/ai/health

The router only ever exposes the AI layer; the graph engine keeps its own
``/api/v1/graph`` surface untouched.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .config import AIConfig
from .providers import AllProvidersUnavailable, NoProviderConfigured
from .schemas import (
    AIHealthResponse,
    ChatRequest,
    ChatResponse,
    InvestigateRequest,
    InvestigationReport,
    InvestigationSummary,
    ProviderStatusResponse,
)
from .service import AIService, InvestigationFailed

logger = logging.getLogger("mulegraph.ai.api")

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


# ====================================================================== #
# dependencies
# ====================================================================== #
def get_ai_service(request: Request) -> AIService:
    service = getattr(request.app.state, "ai_service", None)
    if service is None:
        raise HTTPException(
            status_code=503, detail="AI service is not initialised on this server"
        )
    return service


def _error(status: int, code: str, message: str, detail: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": detail}},
    )


def _map_provider_errors(exc: Exception) -> JSONResponse | None:
    if isinstance(exc, NoProviderConfigured):
        return _error(503, "NO_PROVIDER", str(exc))
    if isinstance(exc, AllProvidersUnavailable):
        return _error(
            503,
            "PROVIDERS_UNAVAILABLE",
            "all AI providers are unavailable; the investigation could not proceed",
            detail=[str(e) for e in exc.errors],
        )
    return None


# ====================================================================== #
# endpoints
# ====================================================================== #
@router.post("/investigate", summary="Run an autonomous investigation")
async def investigate(
    request: InvestigateRequest, service: AIService = Depends(get_ai_service)
) -> Any:
    try:
        if request.stream:
            return StreamingResponse(
                _stream_events(service, request),
                media_type="text/event-stream",
                headers={
                    "cache-control": "no-cache",
                    "x-accel-buffering": "no",
                },
            )
        report = await service.investigate(
            account_ids=request.account_ids,
            transaction_ids=request.transaction_ids,
            question=request.question,
            use_case=request.use_case,
            time_window=request.time_window,
            profile=request.profile,
            max_tool_calls=request.max_tool_calls,
            max_steps=request.max_steps,
        )
        return report
    except (NoProviderConfigured, AllProvidersUnavailable) as exc:
        mapped = _map_provider_errors(exc)
        if mapped is not None:
            logger.warning("investigate blocked: %s", exc)
            return mapped
        raise
    except InvestigationFailed as exc:
        return _error(
            500,
            "INVESTIGATION_FAILED",
            str(exc),
            detail={"investigation_id": exc.investigation_id},
        )
    except ValueError as exc:
        return _error(400, "BAD_REQUEST", str(exc))


async def _stream_events(
    service: AIService, request: InvestigateRequest
) -> AsyncIterator[str]:
    payload = {
        "account_ids": request.account_ids,
        "transaction_ids": request.transaction_ids,
        "question": request.question,
        "use_case": request.use_case,
        "time_window": request.time_window,
        "profile": request.profile,
        "max_tool_calls": request.max_tool_calls,
        "max_steps": request.max_steps,
    }
    try:
        async for event in service.investigate_stream(**payload):
            yield f"data: {json.dumps(event, default=str)}\n\n"
    except (NoProviderConfigured, AllProvidersUnavailable) as exc:
        err = {"type": "error", "code": "PROVIDERS_UNAVAILABLE", "message": str(exc)}
        yield f"data: {json.dumps(err, default=str)}\n\n"
    yield "data: {\"type\": \"end\"}\n\n"


@router.post("/chat", response_model=ChatResponse, summary="Interactive investigator conversation")
async def chat(
    request: ChatRequest, service: AIService = Depends(get_ai_service)
) -> Any:
    try:
        return await service.chat(request)
    except (NoProviderConfigured, AllProvidersUnavailable) as exc:
        mapped = _map_provider_errors(exc)
        if mapped is not None:
            return mapped
        raise
    except InvestigationFailed as exc:
        return _error(
            500,
            "INVESTIGATION_FAILED",
            str(exc),
            detail={"investigation_id": exc.investigation_id},
        )
    except ValueError as exc:
        return _error(400, "BAD_REQUEST", str(exc))


@router.get(
    "/investigation/{investigation_id}",
    response_model=InvestigationSummary,
    summary="Investigation state snapshot",
)
async def get_investigation(
    investigation_id: str, service: AIService = Depends(get_ai_service)
) -> Any:
    try:
        return service.get_investigation(investigation_id)
    except KeyError:
        return _error(404, "NOT_FOUND", f"investigation {investigation_id} not found")


@router.get(
    "/investigation/{investigation_id}/report",
    response_model=InvestigationReport,
    summary="Final structured investigation report",
)
async def get_report(
    investigation_id: str, service: AIService = Depends(get_ai_service)
) -> Any:
    try:
        return service.get_report(investigation_id)
    except KeyError:
        return _error(404, "NOT_FOUND", f"investigation {investigation_id} not found")
    except ValueError as exc:
        return _error(409, "REPORT_NOT_READY", str(exc))


@router.get(
    "/providers/status",
    response_model=ProviderStatusResponse,
    summary="AI provider configuration and health",
)
async def providers_status(service: AIService = Depends(get_ai_service)) -> Any:
    return service.providers_status()


@router.get("/health", response_model=AIHealthResponse, summary="AI layer health")
async def health(service: AIService = Depends(get_ai_service)) -> Any:
    return service.health()


__all__ = ["router", "get_ai_service"]
