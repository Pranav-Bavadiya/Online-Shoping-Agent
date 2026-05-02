"""Background task — removes soft-deleted threads and cleans empty checkpoints."""
import asyncio
from datetime import datetime, timedelta

from app.core.logging import get_logger
from app.db import collections as col

logger = get_logger(__name__)

EMPTY_THREAD_TIMEOUT_HOURS = 24


async def delete_empty_threads() -> int:
    """
    Remove threads that were created but never received any messages
    (no checkpoint) and are older than EMPTY_THREAD_TIMEOUT_HOURS.
    """
    cutoff = datetime.utcnow() - timedelta(hours=EMPTY_THREAD_TIMEOUT_HOURS)
    result = await col.threads().delete_many({
        "is_deleted": True,
        "updated_at": {"$lt": cutoff},
    })
    removed = result.deleted_count
    if removed:
        logger.info("Cleanup: removed stale threads", extra={"count": removed})
    return removed


async def run_cleanup_loop(interval_seconds: int = 3600) -> None:
    """Run cleanup periodically in the background."""
    while True:
        try:
            await delete_empty_threads()
        except Exception as exc:
            logger.error("Cleanup task error", extra={"error": str(exc)})
        await asyncio.sleep(interval_seconds)
