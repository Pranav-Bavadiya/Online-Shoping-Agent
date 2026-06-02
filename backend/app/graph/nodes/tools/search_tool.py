"""Search Tool — multi-marketplace live search used inside chat tool loop."""
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

    all_results = []
    for market in selected:
        provider_cls = _PROVIDER_MAP.get(market)
        if not provider_cls:
            continue
        try:
            provider = provider_cls()
            products = await provider.search(
                keywords=keywords,
                category=category,
                price_min=price_min,
                price_max=price_max,
                limit=50,
            )
            raw = [p.model_dump() for p in products]
            # Annotate commerce fields
            for r in raw:
                source = r.get("source", "")
                r["can_buy_here"] = source == "local"
                r["redirect_url"] = r.get("url", "")
                r["cart_supported"] = True
            all_results.extend(raw)
        except Exception as exc:
            logger.warning("search_tool provider error", extra={"market": market, "error": str(exc)})

    # Store combined results
    if all_results:
        mock_sq = {"category": category, "keywords": keywords, "source": "multi"}
        await _store_raw(mock_sq, all_results, price_min, price_max)

    logger.info("search_tool complete", extra={"count": len(all_results), "markets": selected})
    return {"status": "success", "results": all_results[:10]}
