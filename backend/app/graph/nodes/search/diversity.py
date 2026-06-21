"""Diversity Control Node — ensures brand variety and no duplicates.

Brand cap is bypassed when the user explicitly requests a single brand
(brand_strict is set in structured_query), so we don't filter out their
intentional choice.
"""
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
    "nike", "adidas", "puma", "reebok", "levi", "zara", "h&m",
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

    sq = state.get("structured_query") or {}
    required_types: list[str] = [t.lower().strip() for t in (sq.get("required_types") or [])]
    brand_strict: str = (sq.get("brand_strict") or "").lower().strip()

    # Deduplicate by product_id
    seen_ids: set[str] = set()
    unique = []
    for p in products:
        pid = p.get("product_id", "")
        if pid and pid not in seen_ids:
            seen_ids.add(pid)
            unique.append(p)

    # ── Brand-strict mode ────────────────────────────────────────────────────
    # When the user explicitly asks for a single brand (e.g. "only Samsung"),
    # skip the brand cap entirely so their results aren't filtered down.
    if brand_strict:
        logger.info("Node: diversity — brand_strict mode, skipping cap", extra={
            "brand_strict": brand_strict, "count": len(unique),
            "request_id": state.get("request_id"),
        })
        return {"filtered_results": unique}

    # ── Multi-type: ensure each type bucket is represented ───────────────────
    # Process each type bucket independently before applying global brand cap,
    # so that one type's higher-scored products don't crowd out the other type.
    type_buckets: dict[str, list[dict]] = {rt: [] for rt in required_types}
    general_bucket: list[dict] = []

    if required_types:
        for p in unique:
            title = (p.get("title") or "").lower()
            matched = False
            for rt in required_types:
                if any(word in title for word in rt.split()):
                    type_buckets[rt].append(p)
                    matched = True
                    break
            if not matched:
                general_bucket.append(p)

    # ── Brand cap ────────────────────────────────────────────────────────────
    target = min(len(unique), 50)
    max_per_brand = max(1, int(target * MAX_SAME_BRAND_PERCENT))

    brand_counts: dict[str, int] = {}
    diverse: list[dict] = []

    def _add_with_cap(product_list: list[dict]) -> None:
        for p in product_list:
            brand = _get_brand(p)
            if brand_counts.get(brand, 0) < max_per_brand:
                brand_counts[brand] = brand_counts.get(brand, 0) + 1
                diverse.append(p)

    if required_types:
        # Process each type bucket independently so each type is represented
        for rt in required_types:
            _add_with_cap(type_buckets[rt])
        _add_with_cap(general_bucket)
    else:
        _add_with_cap(unique)

    logger.info("Node: diversity end", extra={
        "count": len(diverse),
        "brands": len(set(_get_brand(p) for p in diverse)),
        "required_types": required_types,
        "brand_strict": brand_strict,
        "request_id": state.get("request_id"),
    })
    return {"filtered_results": diverse}
