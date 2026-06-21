"""Validation & Normalization Node — validates and normalizes structured_query."""
from app.core.logging import get_logger
from app.graph.state import AgentState
from app.utils.normalization import normalize_keywords, normalize_text

logger = get_logger(__name__)


async def validation_node(state: AgentState) -> dict:
    logger.info("Node: validation start", extra={"request_id": state.get("request_id")})

    sq = state.get("structured_query") or {}
    pf = sq.get("price_filter") or {}

    price_min = float(pf.get("min") or 0)
    price_max = float(pf.get("max") or 0)

    # Sanity-check price range
    if price_min < 0:
        price_min = 0.0
    if price_max < 0:
        price_max = 0.0
    if price_max > 0 and price_min > price_max:
        price_min, price_max = 0.0, price_max

    # Determine source based on selected marketplaces
    # Use "multi" when multiple marketplaces are selected so cache lookup finds the right docs.
    selected_markets = sq.get("selected_marketplaces") or state.get("selected_marketplaces") or []
    if len(selected_markets) > 1:
        source = "multi"
    elif len(selected_markets) == 1:
        source = selected_markets[0]
    else:
        source = sq.get("source") or "multi"

    # Normalize required_types — lowercase + strip
    required_types = [t.lower().strip() for t in (sq.get("required_types") or []) if t.strip()]

    # Normalize brand_strict — lowercase + strip
    brand_strict = (sq.get("brand_strict") or "").lower().strip()

    normalized_sq = {
        **sq,
        "category": normalize_text(sq.get("category") or ""),
        "keywords": normalize_keywords(sq.get("keywords") or []),
        "price_filter": {"min": price_min, "max": price_max},
        "source": source,
        "required_types": required_types,
        "brand_strict": brand_strict,
    }

    logger.info("Node: validation end", extra={
        "normalized_query": normalized_sq.get("normalized_query"),
        "source": source,
        "required_types": required_types,
        "brand_strict": brand_strict,
        "request_id": state.get("request_id"),
    })
    return {"structured_query": normalized_sq}
