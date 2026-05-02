"""Product Detail Tool — fetches full product info from cache by product_id."""
from bson import ObjectId

from app.core.logging import get_logger
from app.db import collections as col

logger = get_logger(__name__)


async def product_detail_tool(product_id: str) -> dict:
    """
    Input: product_id
    Logic:
      1. Lookup cache_doc_id from product_lookup_map
      2. Fetch product from product_cache.raw_results
      3. Return product dict or NOT_FOUND
    """
    logger.info("Tool: product_detail called", extra={"product_id": product_id})

    try:
        lookup = await col.product_lookup_map().find_one({"product_id": product_id})
        if not lookup:
            logger.info("Tool: product_detail — not found in lookup", extra={"product_id": product_id})
            return {"status": "NOT_FOUND", "product_id": product_id}

        cache_doc_id = lookup.get("cache_doc_id")
        doc = await col.product_cache().find_one({"_id": ObjectId(cache_doc_id)})
        if not doc:
            return {"status": "NOT_FOUND", "product_id": product_id}

        raw_results = doc.get("raw_results", [])
        for product in raw_results:
            if product.get("product_id") == product_id:
                logger.info("Tool: product_detail — found", extra={"product_id": product_id})
                return {"status": "found", "product": product}

        return {"status": "NOT_FOUND", "product_id": product_id}
    except Exception as exc:
        logger.error("Tool: product_detail error", extra={"error": str(exc), "product_id": product_id})
        return {"status": "NOT_FOUND", "product_id": product_id, "error": str(exc)}
