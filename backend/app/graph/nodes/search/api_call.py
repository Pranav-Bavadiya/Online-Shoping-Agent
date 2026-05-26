"""API Call Node — calls the search provider and stores raw results."""
from datetime import datetime

from app.core.constants import MAX_RAW_PRODUCTS_PER_CACHE
from app.core.logging import get_logger
from app.db import collections as col
from app.graph.state import AgentState
from app.models.product_cache import FiltersUsed, ProductCacheModel, QuerySignature
from app.providers.ebay import EbayProvider
from app.providers.mock import MockProvider

logger = get_logger(__name__)


def _get_provider(source: str):
    if source == "ebay":
        return EbayProvider()
    return MockProvider()


async def api_call_node(state: AgentState) -> dict:
    logger.info("Node: api_call start", extra={"request_id": state.get("request_id")})

    sq = state.get("structured_query") or {}
    keywords = sq.get("keywords") or []
    category = sq.get("category", "")
    pf = sq.get("price_filter") or {}
    price_min = float(pf.get("min") or 0)
    price_max = float(pf.get("max") or 0)
    source = sq.get("source", "ebay")

    # For partial reuse — supplement with extra API call
    retrieval = state.get("retrieval") or {}
    existing_raw = state.get("raw_results") or []

    # Issue #7 fix: for PARTIAL decision, the cache covered [0, cache_price_max].
    # The user wants up to query_price_max. Fetch only the MISSING range:
    # [cache_price_max, query_price_max] so we don't re-fetch what cache already has.
    if retrieval.get("decision") == "partial":
        cache_filters = retrieval.get("cache_filters") or {}
        cache_price_max = float(cache_filters.get("price_max") or 0)
        if cache_price_max > 0:
            # Fetch products priced above the cache ceiling
            price_min = cache_price_max
            logger.info(
                "PARTIAL decision — fetching missing price range",
                extra={"price_min": price_min, "price_max": price_max, "request_id": state.get("request_id")},
            )

    provider = _get_provider(source)

    try:
        new_products = await provider.search(
            keywords=keywords,
            category=category,
            price_min=price_min,
            price_max=price_max,
            limit=MAX_RAW_PRODUCTS_PER_CACHE,
        )
    except Exception as exc:
        logger.error("API call failed", extra={"error": str(exc), "request_id": state.get("request_id")})
        # Return whatever we had from cache (partial), or empty
        return {"raw_results": existing_raw or []}

    # Deduplicate by product_id
    seen_ids = {p.get("product_id") for p in existing_raw if isinstance(p, dict)}
    fresh = [p.model_dump() for p in new_products if p.product_id not in seen_ids]
    combined = (existing_raw + fresh)[:MAX_RAW_PRODUCTS_PER_CACHE]

    # Store to product_cache
    await _store_raw(sq, combined, price_min, price_max)

    logger.info("Node: api_call end", extra={"count": len(combined), "request_id": state.get("request_id")})
    return {"raw_results": combined, "retrieval": {**retrieval, "decision": retrieval.get("decision", "new")}}


async def _store_raw(sq: dict, raw: list[dict], price_min: float, price_max: float) -> None:
    """Persist raw results + build lookup map."""
    try:
        cache_model = ProductCacheModel(
            query_signature=QuerySignature(
                category=sq.get("category", ""),
                keywords=sq.get("keywords", []),
                source=sq.get("source", "ebay"),
            ),
            filters_used=FiltersUsed(price_min=price_min, price_max=price_max),
            raw_results=raw,
            timestamp=datetime.utcnow(),
        )
        result = await col.product_cache().insert_one(cache_model.to_doc())
        cache_doc_id = str(result.inserted_id)

        # Build lookup map entries
        lookup_ops = [
            {
                "product_id": p.get("product_id"),
                "cache_doc_id": cache_doc_id,
            }
            for p in raw if p.get("product_id")
        ]
        for entry in lookup_ops:
            await col.product_lookup_map().update_one(
                {"product_id": entry["product_id"]},
                {"$set": entry},
                upsert=True,
            )
        logger.info("Stored raw cache", extra={"cache_doc_id": cache_doc_id, "count": len(raw)})
    except Exception as exc:
        logger.error("Failed to store raw cache", extra={"error": str(exc)})
