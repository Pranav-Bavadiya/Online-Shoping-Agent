"""Create all MongoDB indexes on startup — idempotent."""
from app.core.config import settings
from app.core.logging import get_logger
from app.db import collections as col

logger = get_logger(__name__)


async def create_indexes() -> None:
    logger.info("Creating MongoDB indexes…")

    # users
    await col.users().create_index("email", unique=True)
    await col.users().create_index("google_id", sparse=True)

    # threads
    await col.threads().create_index([("user_id", 1), ("updated_at", -1)])
    await col.threads().create_index("is_deleted")

    # product_cache — TTL
    await col.product_cache().create_index(
        "timestamp", expireAfterSeconds=settings.cache_ttl_seconds, name="ttl_cache"
    )
    await col.product_cache().create_index([("query_signature.category", 1), ("query_signature.source", 1)])

    # product_lookup_map
    await col.product_lookup_map().create_index("product_id", unique=True)
    await col.product_lookup_map().create_index("cache_doc_id")

    # feedback
    await col.feedback().create_index([("user_id", 1), ("product_id", 1)])
    await col.feedback().create_index("thread_id")
    await col.feedback().create_index("timestamp")

    # sellers
    await col.sellers().create_index("user_id", unique=True)
    await col.sellers().create_index("is_active")

    # local_products
    await col.local_products().create_index("seller_id")
    await col.local_products().create_index("is_active")
    await col.local_products().create_index("category")
    await col.local_products().create_index([("title", "text"), ("description", "text"), ("keywords", "text")])

    # thread_carts (id == thread_id)
    await col.thread_carts().create_index("thread_id", unique=True)
    await col.thread_carts().create_index("user_id")
    await col.thread_carts().create_index("updated_at")

    # orders
    await col.orders().create_index("user_id")
    await col.orders().create_index("thread_id")
    await col.orders().create_index("status")
    await col.orders().create_index("seller_id")
    await col.orders().create_index([("user_id", 1), ("created_at", -1)])
    await col.orders().create_index("razorpay_order_id", sparse=True)

    # payments
    await col.payments().create_index("order_id")
    await col.payments().create_index("user_id")
    await col.payments().create_index("razorpay_order_id", unique=True)
    await col.payments().create_index("status")

    logger.info("MongoDB indexes created")
