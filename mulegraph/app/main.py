"""FastAPI application entry point for the MuleGraph graph engine.

Run:
    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api.routes import router
from .config import GraphConfig
from .graph.builder import GraphBuilder
from .graph.graph_store import GraphStore
from .graph.models import GraphDomainError, LimitExceededError
from .graph.temporal_graph import TemporalGraph
from .intelligence.graph_analyzer import GraphAnalyzer
from .streaming.event_processor import GraphEventProcessor
from .streaming.window_manager import WindowManager
from .storage import GraphPersistenceService, create_repository

logger = logging.getLogger("mulegraph")


def create_services(config: GraphConfig | None = None) -> dict[str, Any]:
    """Assemble the dependency graph of engine components (pure, testable)."""
    config = config or GraphConfig.from_env()
    store = GraphStore(config)
    builder = GraphBuilder(store)
    temporal = TemporalGraph(store)
    analyzer = GraphAnalyzer(store)
    windows = WindowManager()
    repository = create_repository()
    persistence = GraphPersistenceService(store, repository)
    processor = GraphEventProcessor(builder, store, window_manager=windows, sink=None)

    return {
        "config": config,
        "store": store,
        "builder": builder,
        "temporal": temporal,
        "analyzer": analyzer,
        "windows": windows,
        "repository": repository,
        "persistence": persistence,
        "processor": processor,
        "counters": {"started_at": time.time(), "events": 0, "analyses": 0},
    }


def create_app(services: dict[str, Any] | None = None) -> FastAPI:
    services = services or create_services()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "MuleGraph graph engine starting (version %s)", __version__
        )
        yield
        services["analyzer"].close()
        logger.info("MuleGraph graph engine stopped")

    app = FastAPI(
        title="MuleGraph Graph Intelligence Engine",
        version=__version__,
        description=(
            "Real-time UPI money-mule graph analysis: fan-in/fund-out detection, "
            "circular transaction detection, multi-hop money-flow tracing, temporal "
            "motifs, community detection, centrality and explainable risk "
            "propagation. AI-ready structured JSON outputs; no ML/AI providers inside."
        ),
        lifespan=lifespan,
    )
    app.state.services = services
    app.include_router(router)

    # ------------------------- convenience routes ---------------------- #
    @app.get("/", include_in_schema=False)
    async def root() -> JSONResponse:
        return JSONResponse(
            {
                "name": "MuleGraph Graph Intelligence Engine",
                "version": __version__,
                "docs": "/docs",
                "health": "/health",
                "api_base": "/api/v1/graph",
            }
        )

    @app.get("/health", tags=["operational"], summary="Liveness probe (alias of /api/v1/graph/health)")
    async def health_alias() -> JSONResponse:
        return JSONResponse(services["analyzer"].health())


    # ------------------------- error handling ------------------------- #
    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "detail": exc.errors(),
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": f"HTTP_{exc.status_code}",
                    "message": str(exc.detail),
                    "detail": None,
                }
            },
        )

    @app.exception_handler(LookupError)
    async def _not_found(request: Request, exc: LookupError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "NOT_FOUND", "message": str(exc), "detail": None}},
        )

    @app.exception_handler(LimitExceededError)
    async def _limit_exceeded(request: Request, exc: LimitExceededError) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={"error": {"code": "LIMIT_EXCEEDED", "message": str(exc), "detail": None}},
        )

    @app.exception_handler(GraphDomainError)
    async def _domain_error(request: Request, exc: GraphDomainError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "GRAPH_ERROR", "message": str(exc), "detail": None}},
        )

    @app.exception_handler(ValueError)
    async def _bad_request(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "BAD_REQUEST", "message": str(exc), "detail": None}},
        )

    @app.exception_handler(Exception)
    async def _internal_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Unexpected server error",
                    "detail": str(exc),
                }
            },
        )

    return app


app = create_app()
