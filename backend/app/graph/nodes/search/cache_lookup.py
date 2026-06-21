"""Cache Lookup Node — checks MongoDB product_cache for a matching query."""
from app.core.constants import CACHE_KEYWORD_SIMILARITY_THRESHOLD
from app.core.logging import get_logger
from app.db import collections as col
from app.graph.state import AgentState
from app.utils.normalization import keyword_overlap_ratio

logger = get_logger(__name__)


async def cache_lookup_node(state: AgentState) -> dict:
    logger.info("Node: cache_lookup start", extra={"request_id": state.get("request_id")})

    sq = state.get("structured_query") or {}
    category = sq.get("category", "")
    keywords = sq.get("keywords") or []
    # Use the source set by validation_node (could be "multi", "local", "ebay", etc.)
    source = sq.get("source") or "multi"

    # Build cache query — source must match exactly
    query: dict = {"query_signature.source": source}
    if category:
        query["query_signature.category"] = category

    cursor = col.product_cache().find(query, {"_id": 1, "query_signature": 1, "filters_used": 1, "timestamp": 1})
    best_doc_id = None
    best_score = 0.0
    best_meta: dict = {}

    async for doc in cursor:
        cached_keywords = doc.get("query_signature", {}).get("keywords", [])
        score = keyword_overlap_ratio(keywords, cached_keywords)
        if score > best_score and score >= CACHE_KEYWORD_SIMILARITY_THRESHOLD:
            best_score = score
            best_doc_id = str(doc["_id"])
            best_meta = {
                "filters_used": doc.get("filters_used", {}),
                "score": score,
            }

    if best_doc_id:
        logger.info("Node: cache_lookup — hit", extra={
            "cache_doc_id": best_doc_id,
            "score": best_meta.get("score"),
            "source": source,
            "request_id": state.get("request_id"),
        })
        return {
            "retrieval": {
                "cache_hit": True,
                "decision": "pending",
                "cache_doc_id": best_doc_id,
                "cache_filters": best_meta.get("filters_used", {}),
            }
        }

    logger.info("Node: cache_lookup — miss", extra={"source": source, "request_id": state.get("request_id")})
    return {"retrieval": {"cache_hit": False, "decision": "new", "cache_doc_id": None}}
