"""Create all MongoDB indexes (including TTL) on startup."""
from app.core.config import settings
from app.core.logging import get_logger
from app.db import collections as col

logger = get_logger(__name__)


async def create_indexes() -> None:
    """Idempotent — safe to call every startup."""
    logger.info("Creating MongoDB indexes…")

    # users
    await col.users().create_index("email", unique=True)
    await col.users().create_index("google_id", sparse=True)

    # threads
    await col.threads().create_index([("user_id", 1), ("updated_at", -1)])
    await col.threads().create_index("is_deleted")

    # product_cache — TTL on `timestamp` field
    await col.product_cache().create_index(
        "timestamp",
        expireAfterSeconds=settings.cache_ttl_seconds,
        name="ttl_cache",
    )
    await col.product_cache().create_index([
        ("query_signature.category", 1),
        ("query_signature.source", 1),
    ])

    # product_lookup_map
    await col.product_lookup_map().create_index("product_id", unique=True)
    await col.product_lookup_map().create_index("cache_doc_id")

    # feedback
    await col.feedback().create_index([("user_id", 1), ("product_id", 1)])
    await col.feedback().create_index("thread_id")
    await col.feedback().create_index("timestamp")

    logger.info("MongoDB indexes created")
