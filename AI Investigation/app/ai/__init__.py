"""MuleGraph AI investigation layer.

A provider-independent, autonomous financial investigator built on LangGraph.
The AI layer treats the graph engine's public APIs as read-only investigation
tools and never mutates graph state.

Layout:
    config      - environment driven configuration (keys stay in env vars)
    schemas     - strict Pydantic schemas (plan, evidence, final report, API DTOs)
    providers   - Google Gemini + Hugging Face adapters and the fallback manager
    tools       - validated, bounded read-only graph investigation tools
    prompts     - dedicated prompt files (kept out of code)
    workflow    - LangGraph state, nodes, conditional routing, runner
    service     - facade used by the FastAPI router (app/ai/api.py)
"""

from .config import AIConfig

__all__ = ["AIConfig"]
