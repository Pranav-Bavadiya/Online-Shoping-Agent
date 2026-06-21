"""Search Tool — multi-marketplace live search used inside chat tool loop.

Mirrors the api_call_node behaviour:
- Per-type separate searches when required_types is set.
- Hard brand filter when brand_strict is set.
"""
from app.core.logging import get_logger
from app.graph.nodes.search.api_call import _store_raw
from app.providers.ebay import EbayProvider
from app.providers.local import LocalMarketplaceProvider
from app.providers.mock import MockProvider

logger = get_logger(__name__)

_PROVIDER_MAP = {
    "ebay": EbayProvider,
    "local": LocalMarketplaceProvider,
    "mock": MockProvider,
}


async def search_tool(query: str, structured_query: dict | None = None) -> dict:
    sq = structured_query or {}
    keywords = sq.get("keywords") or [q.strip() for q in query.split() if q.strip()]
    category = sq.get("category", "")
    pf = sq.get("price_filter") or {}
    price_min = float(pf.get("min") or 0)
    price_max = float(pf.get("max") or 0)
    selected = sq.get("selected_marketplaces") or ["ebay", "mock"]
    required_types: list[str] = [t.lower().strip() for t in (sq.get("required_types") or []) if t.strip()]
    brand_strict: str = (sq.get("brand_strict") or "").lower().strip()

    # Build search batches — per type if required_types set, else single combined search
    if required_types:
        search_batches = [(rt.split(), rt) for rt in required_types]
    else:
        search_batches = [(keywords, "single")]

    per_type_limit = max(50 // max(len(search_batches), 1), 20)

    seen_ids: set[str] = set()
    all_results: list[dict] = []

    for batch_keywords, batch_label in search_batches:
        for market in selected:
            provider_cls = _PROVIDER_MAP.get(market)
            if not provider_cls:
                continue
            try:
                provider = provider_cls()
                products = await provider.search(
                    keywords=batch_keywords,
                    category=category,
                    price_min=price_min,
                    price_max=price_max,
                    limit=per_type_limit,
                )
                for p in products:
                    if p.product_id not in seen_ids:
                        seen_ids.add(p.product_id)
                        raw = p.model_dump()
                        source = raw.get("source", "")
                        raw["can_buy_here"] = source == "local"
                        raw["redirect_url"] = raw.get("url", "")
                        raw["cart_supported"] = True
                        all_results.append(raw)
            except Exception as exc:
                logger.warning("search_tool provider error", extra={
                    "market": market, "batch": batch_label, "error": str(exc)
                })

    # Apply brand_strict filter inline (mirrors filtering_node behaviour)
    if brand_strict:
        filtered = []
        for p in all_results:
            title = (p.get("title") or "").lower()
            raw_attrs = p.get("raw_attributes") or {}
            prod_brand = (raw_attrs.get("brand") or "").lower()
            prod_cat = (p.get("category") or "").lower()
            if brand_strict in title or brand_strict in prod_brand or brand_strict in prod_cat:
                filtered.append(p)
        all_results = filtered
        logger.info("search_tool: brand_strict filter applied", extra={
            "brand_strict": brand_strict, "count": len(all_results)
        })

    # Store combined results in cache for future reuse
    if all_results:
        mock_sq = {"category": category, "keywords": keywords, "source": "multi"}
        await _store_raw(mock_sq, all_results, price_min, price_max)

    logger.info("search_tool complete", extra={
        "count": len(all_results), "markets": selected,
        "required_types": required_types, "brand_strict": brand_strict,
    })
    return {"status": "success", "results": all_results[:20]}
