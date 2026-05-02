"""Feedback service — store and retrieve user feedback."""
from datetime import datetime
from typing import Optional

from app.core.constants import FEEDBACK_CLICK, FEEDBACK_IGNORE, FEEDBACK_LIKE
from app.core.logging import get_logger
from app.db import collections as col
from app.models.feedback import FeedbackModel
from app.utils.uuid import new_uuid

logger = get_logger(__name__)


async def record_feedback(user_id: str, thread_id: str, product_id: str, action: str) -> None:
    fb = FeedbackModel(
        id=new_uuid(),
        user_id=user_id,
        thread_id=thread_id,
        product_id=product_id,
        action=action,
        timestamp=datetime.utcnow(),
    )
    await col.feedback().insert_one(fb.to_doc())
    logger.info("Feedback recorded", extra={"user_id": user_id, "product_id": product_id, "action": action})


async def get_feedback_summary(user_id: str, product_ids: list[str]) -> dict[str, dict]:
    """Return feedback summary: {product_id: {like: bool, click: bool, ignore: bool}}"""
    cursor = col.feedback().find({
        "user_id": user_id,
        "product_id": {"$in": product_ids},
    })
    summary: dict[str, dict] = {}
    async for doc in cursor:
        pid = doc["product_id"]
        action = doc["action"]
        if pid not in summary:
            summary[pid] = {FEEDBACK_LIKE: False, FEEDBACK_CLICK: False, FEEDBACK_IGNORE: False}
        summary[pid][action] = True
    return summary
