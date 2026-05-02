"""Background analytics task — aggregates feedback data (stub for future expansion)."""
import asyncio

from app.core.logging import get_logger
from app.db import collections as col

logger = get_logger(__name__)


async def compute_popular_products(limit: int = 50) -> list[dict]:
    """Aggregate most-liked products across all users."""
    pipeline = [
        {"$match": {"action": "like"}},
        {"$group": {"_id": "$product_id", "likes": {"$sum": 1}}},
        {"$sort": {"likes": -1}},
        {"$limit": limit},
    ]
    cursor = col.feedback().aggregate(pipeline)
    return [doc async for doc in cursor]


async def run_analytics_loop(interval_seconds: int = 7200) -> None:
    """Run analytics aggregation periodically."""
    while True:
        try:
            popular = await compute_popular_products()
            logger.info("Analytics: popular products computed", extra={"count": len(popular)})
        except Exception as exc:
            logger.error("Analytics task error", extra={"error": str(exc)})
        await asyncio.sleep(interval_seconds)
