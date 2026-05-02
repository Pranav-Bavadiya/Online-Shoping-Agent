"""Diversity Control Node — ensures brand variety and no duplicates."""
from app.core.constants import MAX_SAME_BRAND_PERCENT, MIN_BRANDS_IN_RESULTS
from app.core.logging import get_logger
from app.graph.state import AgentState

logger = get_logger(__name__)

# Common brand patterns for extraction
KNOWN_BRANDS = {
    "apple", "samsung", "sony", "lg", "hp", "dell", "lenovo", "asus",
    "microsoft", "google", "amazon", "beats", "bose", "jbl", "pioneer",
    "panasonic", "philips", "sharp", "toshiba", "canon", "nikon",
    "moto", "oneplus", "nokia", "oppo", "vivo", "xiaomi", "realme",
}


def _get_brand(product: dict) -> str:
    """Extract brand from product using multiple strategies."""
    # Strategy 1: Check raw_attributes
    raw_attrs = product.get("raw_attributes") or {}
    brand = raw_attrs.get("brand") or ""
    if brand:
        return brand.lower().strip()

    # Strategy 2: Extract from title - look for known brands first
    title = product.get("title", "").lower()
    for known_brand in KNOWN_BRANDS:
        if known_brand in title:
            return known_brand

    # Strategy 3: Category-based fallback
    category = (product.get("category") or "").lower()
    if category:
        parts = category.split()
        if parts:
            return parts[0]

    # Strategy 4: First meaningful word from title (if at least 3 chars)
    title_words = [w for w in title.split() if len(w) > 2]
    if title_words:
        return title_words[0]

    return "unknown"


async def diversity_node(state: AgentState) -> dict:
    logger.info("Node: diversity start", extra={"request_id": state.get("request_id")})

    products = list(state.get("filtered_results") or [])
    if not products:
        return {"filtered_results": []}

    # Deduplicate by product_id
    seen_ids: set[str] = set()
    unique = []
    for p in products:
        pid = p.get("product_id", "")
        if pid and pid not in seen_ids:
            seen_ids.add(pid)
            unique.append(p)

    # Brand cap: no brand > MAX_SAME_BRAND_PERCENT of final results
    target = min(len(unique), 50)
    max_per_brand = max(1, int(target * MAX_SAME_BRAND_PERCENT))

    brand_counts: dict[str, int] = {}
    diverse: list[dict] = []
    overflow: list[dict] = []

    for p in unique:
        brand = _get_brand(p)
        if brand_counts.get(brand, 0) < max_per_brand:
            brand_counts[brand] = brand_counts.get(brand, 0) + 1
            diverse.append(p)
        else:
            overflow.append(p)

    # If we haven't hit minimum unique brands, add overflow items from other brands
    unique_brands = len(set(_get_brand(p) for p in diverse))
    if unique_brands < MIN_BRANDS_IN_RESULTS and overflow:
        brand_set = {_get_brand(p) for p in diverse}
        for p in overflow:
            b = _get_brand(p)
            if b not in brand_set:
                diverse.append(p)
                brand_set.add(b)
                if len(brand_set) >= MIN_BRANDS_IN_RESULTS:
                    break

    logger.info("Node: diversity end", extra={
        "count": len(diverse),
        "brands": len(set(_get_brand(p) for p in diverse)),
        "request_id": state.get("request_id"),
    })
    return {"filtered_results": diverse}
