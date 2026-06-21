"""Filtering Node — applies price, category, and brand filters to raw results."""
from app.core.logging import get_logger
from app.graph.state import AgentState

logger = get_logger(__name__)


async def filtering_node(state: AgentState) -> dict:
    logger.info("Node: filtering start", extra={"request_id": state.get("request_id")})

    raw = state.get("raw_results") or []
    sq = state.get("structured_query") or {}
    pf = sq.get("price_filter") or {}
    price_min = float(pf.get("min") or 0)
    price_max = float(pf.get("max") or 0)
    category = (sq.get("category") or "").lower().strip()
    required_types: list[str] = [t.lower().strip() for t in (sq.get("required_types") or [])]
    brand_strict: str = (sq.get("brand_strict") or "").lower().strip()

    filtered = []
    for p in raw:
        price_info = p.get("price") or {}
        price_val = float(price_info.get("value") or 0)

        # Price filter
        if price_min > 0 and price_val < price_min:
            continue
        if price_max > 0 and price_val > price_max:
            continue

        prod_title = (p.get("title") or "").lower()
        prod_cat = (p.get("category") or "").lower()
        raw_attrs = p.get("raw_attributes") or {}
        prod_brand = (raw_attrs.get("brand") or "").lower()

        # ── Brand-strict filter ──────────────────────────────────────────────
        # When user said "only <brand>", hard-filter to products matching that brand
        # in title, brand attribute, or category.
        if brand_strict:
            if (brand_strict not in prod_title
                    and brand_strict not in prod_brand
                    and brand_strict not in prod_cat):
                continue

        # ── Required-types filter ────────────────────────────────────────────
        # If query has required_types, a product passes if it matches ANY required type
        if required_types:
            matches_required = any(
                any(word in prod_title for word in rt.split())
                for rt in required_types
            )
            if matches_required:
                filtered.append(p)
                continue
            # Still allow if it matches general keywords (don't over-filter)
            keywords = sq.get("keywords") or []
            if any(kw in prod_title for kw in keywords):
                filtered.append(p)
            continue

        # ── Standard category filter (soft — substring match) ────────────────
        if category:
            if category not in prod_cat and category not in prod_title:
                keywords = sq.get("keywords") or []
                if not any(kw in prod_title for kw in keywords):
                    continue

        filtered.append(p)

    # Relaxed filtering fallback — if too few results, relax price 20%
    # (only when brand_strict is not set, to avoid breaking explicit brand queries)
    if len(filtered) < 3 and price_max > 0 and not brand_strict:
        relaxed_max = price_max * 1.2
        filtered = []
        for p in raw:
            price_info = p.get("price") or {}
            price_val = float(price_info.get("value") or 0)
            if price_min > 0 and price_val < price_min:
                continue
            if price_val > relaxed_max:
                continue
            filtered.append(p)
        logger.info("Node: filtering — relaxed filter applied", extra={"count": len(filtered)})

    logger.info("Node: filtering end", extra={
        "filtered": len(filtered), "raw": len(raw),
        "brand_strict": brand_strict,
        "request_id": state.get("request_id"),
    })
    return {"filtered_results": _enrich_commerce_fields(filtered)}


def _enrich_commerce_fields(products: list[dict]) -> list[dict]:
    """Lift can_buy_here/redirect_url from raw_attributes if not already top-level."""
    for p in products:
        attrs = p.get("raw_attributes") or {}
        if "can_buy_here" not in p:
            p["can_buy_here"] = attrs.get("can_buy_here", p.get("source") == "local")
        if "redirect_url" not in p:
            p["redirect_url"] = attrs.get("redirect_url", p.get("url", ""))
        if "cart_supported" not in p:
            p["cart_supported"] = attrs.get("cart_supported", True)
    return products
