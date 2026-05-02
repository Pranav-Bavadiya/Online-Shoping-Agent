"""Thread service — CRUD for conversation threads."""
from datetime import datetime
from typing import Optional

from app.core.constants import MAX_THREAD_LIST_LIMIT
from app.core.logging import get_logger
from app.db import collections as col
from app.exceptions.base import ForbiddenError, NotFoundError
from app.utils.uuid import new_thread_id

logger = get_logger(__name__)


async def list_threads(user_id: str, limit: int = MAX_THREAD_LIST_LIMIT) -> list[dict]:
    cursor = col.threads().find(
        {"user_id": user_id, "is_deleted": False},
        {"_id": 0, "thread_id": 1, "title": 1, "updated_at": 1},
    ).sort("updated_at", -1).limit(limit)
    return [doc async for doc in cursor]


async def get_thread(thread_id: str, user_id: str) -> dict:
    doc = await col.threads().find_one({"thread_id": thread_id, "is_deleted": False})
    if not doc:
        raise NotFoundError("Thread not found")
    if doc["user_id"] != user_id:
        raise ForbiddenError("Access denied")
    return doc


async def create_thread(user_id: str, title: str) -> str:
    tid = new_thread_id()
    now = datetime.utcnow()
    await col.threads().insert_one({
        "_id": tid,
        "thread_id": tid,
        "user_id": user_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "is_deleted": False,
    })
    logger.info("Thread created", extra={"thread_id": tid, "user_id": user_id})
    return tid


async def touch_thread(thread_id: str) -> None:
    await col.threads().update_one(
        {"thread_id": thread_id},
        {"$set": {"updated_at": datetime.utcnow()}},
    )


async def rename_thread(thread_id: str, user_id: str, title: str) -> None:
    doc = await get_thread(thread_id, user_id)   # raises if not found / forbidden
    await col.threads().update_one(
        {"thread_id": thread_id},
        {"$set": {"title": title, "updated_at": datetime.utcnow()}},
    )


async def delete_thread(thread_id: str, user_id: str) -> None:
    doc = await get_thread(thread_id, user_id)
    await col.threads().update_one(
        {"thread_id": thread_id},
        {"$set": {"is_deleted": True, "updated_at": datetime.utcnow()}},
    )
    logger.info("Thread soft-deleted", extra={"thread_id": thread_id, "user_id": user_id})


async def verify_thread_ownership(thread_id: str, user_id: str) -> dict:
    """Returns thread doc if owned by user, raises otherwise."""
    return await get_thread(thread_id, user_id)
