"""Standalone FastAPI application for the MuleGraph AI investigator.

Run from this directory with ``uvicorn app.main:app``. The graph engine is
accessed only through its HTTP API; no graph-engine package is required here.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from .ai.api import router as ai_router
from .ai.config import AIConfig
from .ai.service import create_ai_service


def create_app(config: AIConfig | None = None) -> FastAPI:
    config = config or AIConfig.from_env()
    if not config.graph_api_url:
        raise ValueError(
            "Set MULEGRAPH_AI_GRAPH_API_URL to the MuleGraph graph API base URL "
            "before starting the standalone AI service."
        )
    service = create_ai_service(None, config)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await service.aclose()

    app = FastAPI(
        title="MuleGraph AI Investigator",
        description=(
            "Autonomous, read-only financial investigations. Graph evidence is "
            "retrieved from a separately running MuleGraph graph API."
        ),
        lifespan=lifespan,
    )
    app.state.ai_service = service
    app.include_router(ai_router)
    return app


app = create_app()
