"""LangGraph pipeline builder — assembles the full agent graph."""
from langgraph.graph import StateGraph, END, START

from app.core.logging import get_logger
from app.graph.state import AgentState
from app.graph.nodes.query_understanding import query_understanding_node
from app.graph.nodes.disambiguation import disambiguation_node, should_clarify
from app.graph.nodes.intent_router import intent_router_node, route_by_intent
from app.graph.nodes.final_response import clarification_response_node
from app.graph.nodes.search.validation import validation_node
from app.graph.nodes.search.cache_lookup import cache_lookup_node
from app.graph.nodes.search.decision_engine import decision_engine_node, route_cache_decision
from app.graph.nodes.search.api_call import api_call_node
from app.graph.nodes.search.filtering import filtering_node
from app.graph.nodes.search.diversity import diversity_node
from app.graph.nodes.search.ranking import ranking_node
from app.graph.nodes.search.formatter import formatter_node
from app.graph.nodes.tools.tool_loop import tool_loop_node, should_continue_tool_loop

logger = get_logger(__name__)


def build_graph() -> StateGraph:
    """Build and compile the shopping agent LangGraph."""
    graph = StateGraph(AgentState)

    # ── Add all nodes ───────────────────────────────────────────────────────
    graph.add_node("query_understanding", query_understanding_node)
    graph.add_node("disambiguation", disambiguation_node)
    graph.add_node("clarification_response", clarification_response_node)
    graph.add_node("intent_router", intent_router_node)

    # Search pipeline nodes
    graph.add_node("validation", validation_node)
    graph.add_node("cache_lookup", cache_lookup_node)
    graph.add_node("decision_engine", decision_engine_node)
    graph.add_node("api_call", api_call_node)
    graph.add_node("filtering", filtering_node)
    graph.add_node("diversity", diversity_node)
    graph.add_node("ranking", ranking_node)
    graph.add_node("formatter", formatter_node)

    # Chat / tool loop node
    graph.add_node("tool_loop", tool_loop_node)

    # ── Entry point ──────────────────────────────────────────────────────────
    graph.add_edge(START, "query_understanding")

    # ── Query Understanding → Disambiguation ─────────────────────────────────
    graph.add_edge("query_understanding", "disambiguation")

    # ── Disambiguation → clarify or continue ─────────────────────────────────
    graph.add_conditional_edges(
        "disambiguation",
        should_clarify,
        {
            "clarify": "clarification_response",
            "continue": "intent_router",
        },
    )

    # Clarification response ends the turn (user must reply)
    graph.add_edge("clarification_response", END)

    # ── Intent Router → search or chat ───────────────────────────────────────
    graph.add_conditional_edges(
        "intent_router",
        route_by_intent,
        {
            "search": "validation",
            "chat": "tool_loop",
        },
    )

    # ── Search Pipeline ───────────────────────────────────────────────────────
    graph.add_edge("validation", "cache_lookup")
    graph.add_edge("cache_lookup", "decision_engine")

    graph.add_conditional_edges(
        "decision_engine",
        route_cache_decision,
        {
            "filtering": "filtering",   # reuse → skip API
            "api_call": "api_call",     # new / partial → call API
        },
    )

    graph.add_edge("api_call", "filtering")
    graph.add_edge("filtering", "diversity")
    graph.add_edge("diversity", "ranking")
    graph.add_edge("ranking", "formatter")
    graph.add_edge("formatter", END)

    # ── Chat / Tool Loop ──────────────────────────────────────────────────────
    graph.add_conditional_edges(
        "tool_loop",
        should_continue_tool_loop,
        {
            "loop": "tool_loop",   # iterate
            "done": END,           # done
        },
    )

    logger.info("LangGraph pipeline built successfully")
    return graph.compile()


# Singleton compiled graph
shopping_graph = build_graph()
