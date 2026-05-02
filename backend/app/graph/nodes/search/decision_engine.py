"""Decision Engine Node — decides reuse / partial / new based on cache vs query price."""
from app.core.constants import DECISION_NEW, DECISION_PARTIAL, DECISION_REUSE
from app.core.logging import get_logger
from app.db import collections as col
from app.graph.state import AgentState
from bson import ObjectId

logger = get_logger(__name__)


async def decision_engine_node(state: AgentState) -> dict:
    logger.info("Node: decision_engine start", extra={"request_id": state.get("request_id")})

    retrieval = state.get("retrieval") or {}
    sq = state.get("structured_query") or {}

    if not retrieval.get("cache_hit"):
        logger.info("Node: decision_engine — no cache, new", extra={"request_id": state.get("request_id")})
        return {"retrieval": {**retrieval, "decision": DECISION_NEW}}

    cache_doc_id =  retrieval.get("cache_doc_id")
    cache_filters = retrieval.get("cache_filters") or {}

    query_price_max = (sq.get("price_filter") or {}).get("max", 0)
    cache_price_max = float(cache_filters.get("price_max") or 0)

    # Decision logic per spec:
    # cache_price >= query_price → reuse (cache covers stricter filter)
    # cache_price < query_price → partial (cache narrower; may need more data)
    # no cache → new

    if cache_price_max == 0 or (query_price_max > 0 and cache_price_max >= query_price_max):
        decision = DECISION_REUSE
    elif query_price_max == 0 or cache_price_max < query_price_max:
        decision = DECISION_PARTIAL
    else:
        decision = DECISION_REUSE

    # For REUSE or PARTIAL — load raw_results from cache now
    if decision == DECISION_REUSE or decision == DECISION_PARTIAL:
        try:
            doc = await col.product_cache().find_one({"_id": ObjectId(cache_doc_id)})
            raw = doc.get("raw_results", []) if doc else []
            logger.info("Node: decision_engine — loaded cache", extra={
                "decision": decision, "products": len(raw),
                "request_id": state.get("request_id"),
            })
            return {"retrieval": {**retrieval, "decision": decision}, "raw_results": raw}
        except Exception as exc:
            logger.warning("Decision engine failed to load cache", extra={"error": str(exc)})
            # Fall back to new API call
            return {"retrieval": {**retrieval, "decision": DECISION_NEW}, "raw_results": None}

    logger.info("Node: decision_engine", extra={"decision": decision, "request_id": state.get("request_id")})
    return {"retrieval": {**retrieval, "decision": decision}}


def route_cache_decision(state: AgentState) -> str:
    """Conditional edge after decision engine."""
    retrieval = state.get("retrieval") or {}
    decision = retrieval.get("decision", DECISION_NEW)
    if decision == DECISION_REUSE:
        return "filtering"   # skip API call
    return "api_call"        # partial or new → call API
