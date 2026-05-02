"""Search Tool — executes a fresh API search (used inside chat tool loop)."""
from app.core.logging import get_logger
from app.graph.nodes.search.api_call import _store_raw
from app.graph.state import AgentState
from app.providers.ebay import EbayProvider
from app.providers.mock import MockProvider
from app.utils.normalization import normalize_text

logger = get_logger(__name__)


async def search_tool(query: str, structured_query: dict | None = None) -> dict:
    """
    Input: query string or structured_query
    Logic:
      1. Call API only
      2. Store RAW data
      3. Return results
    """
    logger.info("Tool: search_tool called", extra={"query": query})

    sq = structured_query or {}
    keywords = sq.get("keywords") or [q.strip() for q in query.split() if q.strip()]
    category = sq.get("category", "")
    pf = sq.get("price_filter") or {}
    price_min = float(pf.get("min") or 0)
    price_max = float(pf.get("max") or 0)
    source = sq.get("source", "ebay")

    provider = EbayProvider() if source == "ebay" else MockProvider()

    try:
        products = await provider.search(
            keywords=keywords,
            category=category,
            price_min=price_min,
            price_max=price_max,
            limit=50,
        )
        raw = [p.model_dump() for p in products]
        mock_sq = {"category": category, "keywords": keywords, "source": source}
        await _store_raw(mock_sq, raw, price_min, price_max)
        logger.info("Tool: search_tool success", extra={"count": len(raw)})
        return {"status": "success", "results": raw[:10]}
    except Exception as exc:
        logger.error("Tool: search_tool error", extra={"error": str(exc)})
        return {"status": "error", "results": [], "error": str(exc)}
