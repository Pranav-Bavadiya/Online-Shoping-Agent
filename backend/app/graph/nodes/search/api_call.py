"""API Call Node — multi-marketplace product search with partial cache support."""
from datetime import datetime

from app.core.constants import MAX_RAW_PRODUCTS_PER_CACHE
from app.core.logging import get_logger
from app.db import collections as col
from app.graph.state import AgentState
from app.models.product_cache import FiltersUsed, ProductCacheModel, QuerySignature
from app.providers.ebay import EbayProvider
from app.providers.local import LocalMarketplaceProvider
from app.providers.mock import MockProvider

logger = get_logger(__name__)

_PROVIDER_MAP = {
    "ebay": EbayProvider,
    "local": LocalMarketplaceProvider,
    "mock": MockProvider,
}


async def api_call_node(state: AgentState) -> dict:
    logger.info("Node: api_call start", extra={"request_id": state.get("request_id")})

    sq = state.get("structured_query") or {}
    keywords = sq.get("keywords") or []
    category = sq.get("category", "")
    pf = sq.get("price_filter") or {}
    price_min = float(pf.get("min") or 0)
    price_max = float(pf.get("max") or 0)
    required_types: list[str] = [t.lower().strip() for t in (sq.get("required_types") or [])]

    # Determine selected marketplaces from state (thread preference)
    selected_markets = (
        state.get("selected_marketplaces")
        or sq.get("selected_marketplaces")
        or ["ebay", "mock"]
    )

    retrieval = state.get("retrieval") or {}
    existing_raw = state.get("raw_results") or []

    # For PARTIAL, fetch only the missing price range
    if retrieval.get("decision") == "partial":
        cache_filters = retrieval.get("cache_filters") or {}
        cache_price_max = float(cache_filters.get("price_max") or 0)
        if cache_price_max > 0:
            price_min = cache_price_max
            logger.info("PARTIAL: adjusting price_min", extra={"price_min": price_min})

    all_new: list[dict] = []
    seen_ids = {p.get("product_id") for p in existing_raw if isinstance(p, dict)}

    # If multiple required_types, search separately for each type so providers
    # can return relevant items for each type independently.
    # Otherwise do a single combined search.
    if required_types:
        search_batches = [
            (rt.split(), rt)          # (keywords_for_this_type, label)
            for rt in required_types
        ]
        logger.info("api_call: multi-type search", extra={
            "required_types": required_types, "request_id": state.get("request_id")
        })
    else:
        search_batches = [(keywords, "single")]

    per_type_limit = max(
        MAX_RAW_PRODUCTS_PER_CACHE // max(len(search_batches), 1),
        50,
    )

    for batch_keywords, batch_label in search_batches:
        for market in selected_markets:
            provider_cls = _PROVIDER_MAP.get(market)
            if not provider_cls:
                continue
            try:
                provider = provider_cls()
                products = await provider.search(
                    keywords=batch_keywords, category=category,
                    price_min=price_min, price_max=price_max,
                    limit=per_type_limit,
                )
                for p in products:
                    if p.product_id not in seen_ids:
                        seen_ids.add(p.product_id)
                        raw = p.model_dump()
                        raw["can_buy_here"] = p.source == "local"
                        raw["redirect_url"] = raw.get("url", "")
                        raw["cart_supported"] = True
                        all_new.append(raw)
            except Exception as exc:
                logger.warning("api_call provider error", extra={
                    "market": market, "batch": batch_label, "error": str(exc)
                })

    # Store the union (existing + new) in the cache for future reuse — but only
    # pass the freshly-fetched results to downstream nodes so filters/ranking
    # work on current data, not stale products from a previous query.
    combined_for_cache = (existing_raw + all_new)[:MAX_RAW_PRODUCTS_PER_CACHE]
    await _store_raw(sq, combined_for_cache, price_min, price_max)

    # Downstream (filtering → diversity → ranking → formatter) should see only
    # the new results from this request.  For a PARTIAL cache hit the upstream
    # cache_lookup node already put the cached slice into filtered_results; the
    # api_call node just adds the missing range here.
    results_for_pipeline = all_new[:MAX_RAW_PRODUCTS_PER_CACHE]

    logger.info("Node: api_call end", extra={"new": len(all_new), "cached": len(existing_raw)})
    return {"raw_results": results_for_pipeline, "retrieval": {**retrieval, "decision": retrieval.get("decision", "new")}}


async def _store_raw(sq: dict, raw: list[dict], price_min: float, price_max: float) -> None:
    try:
        cache_model = ProductCacheModel(
            query_signature=QuerySignature(
                category=sq.get("category", ""),
                keywords=sq.get("keywords", []),
                source=sq.get("source", "multi"),
            ),
            filters_used=FiltersUsed(price_min=price_min, price_max=price_max),
            raw_results=raw,
            timestamp=datetime.utcnow(),
        )
        result = await col.product_cache().insert_one(cache_model.to_doc())
        cache_doc_id = str(result.inserted_id)
        for p in raw:
            if p.get("product_id"):
                await col.product_lookup_map().update_one(
                    {"product_id": p["product_id"]},
                    {"$set": {"product_id": p["product_id"], "cache_doc_id": cache_doc_id}},
                    upsert=True,
                )
    except Exception as exc:
        logger.error("Failed to store raw cache", extra={"error": str(exc)})
