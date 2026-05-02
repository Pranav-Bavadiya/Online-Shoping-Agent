"""Cache service — helpers for reading/writing product cache."""
from typing import Optional
from bson import ObjectId

from app.core.logging import get_logger
from app.db import collections as col

logger = get_logger(__name__)


async def get_cache_doc(cache_doc_id: str) -> Optional[dict]:
    try:
        doc = await col.product_cache().find_one({"_id": ObjectId(cache_doc_id)})
        return doc
    except Exception as exc:
        logger.error("get_cache_doc failed", extra={"error": str(exc)})
        return None


async def get_product_from_cache(product_id: str) -> Optional[dict]:
    """Return a single raw product from cache via lookup map."""
    lookup = await col.product_lookup_map().find_one({"product_id": product_id})
    if not lookup:
        return None
    doc = await get_cache_doc(lookup["cache_doc_id"])
    if not doc:
        return None
    for p in doc.get("raw_results", []):
        if p.get("product_id") == product_id:
            return p
    return None
