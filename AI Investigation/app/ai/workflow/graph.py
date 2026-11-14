"""LangGraph investigation workflow: conditional routing, not a fixed chain.

    START -> intake -> plan -> act  --(enough evidence)--> correlate
                          ^         |
                          |         +--(budget/limits)------> conclude -> report -> END
                          +-------- (more evidence needed) --+

Routing decisions are made from live state (budget, decisions, stall
detection), so the investigation adapts to tool results instead of following
a hardcoded sequence.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import AIContext, InvestigationNodes
from .state import InvestigationState


def build_investigation_graph(ctx: AIContext):
    """Compile the investigation workflow bound to an AI context."""
    nodes = InvestigationNodes(ctx)

    graph: StateGraph = StateGraph(InvestigationState)
    graph.add_node("intake", nodes.intake)
    graph.add_node("plan", nodes.plan)
    graph.add_node("act", nodes.act)
    graph.add_node("correlate", nodes.correlate)
    graph.add_node("conclude", nodes.conclude)
    graph.add_node("report", nodes.report)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "plan")
    graph.add_edge("plan", "act")
    graph.add_conditional_edges(
        "act",
        nodes.route_after_act,
        {
            "act": "act",
            "correlate": "correlate",
            "conclude": "conclude",
        },
    )
    graph.add_edge("correlate", "conclude")
    graph.add_edge("conclude", "report")
    graph.add_edge("report", END)

    return graph.compile()


__all__ = ["build_investigation_graph"]
