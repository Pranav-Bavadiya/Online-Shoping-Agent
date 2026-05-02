"""MongoDB-backed LangGraph checkpointer.

Stores/loads graph state keyed by thread_id so conversation
context persists across API requests.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from app.core.logging import get_logger
from app.db.client import get_database
from app.graph.checkpointer.serializer import deserialize_state, serialize_state

logger = get_logger(__name__)

CHECKPOINTS_COLLECTION = "checkpoints"


class MongoCheckpointer:
    """Simple async checkpointer — saves/loads full graph state to MongoDB."""

    def __init__(self):
        self._col = None

    def _collection(self):
        if self._col is None:
            self._col = get_database()[CHECKPOINTS_COLLECTION]
        return self._col

    async def load(self, thread_id: str) -> Optional[dict]:
        """Load state for thread_id. Returns None if not found."""
        try:
            doc = await self._collection().find_one({"thread_id": thread_id})
            if doc and "state" in doc:
                state = deserialize_state(doc["state"])
                logger.info("Checkpointer: state loaded", extra={"thread_id": thread_id})
                return state
        except Exception as exc:
            logger.error("Checkpointer load failed", extra={"thread_id": thread_id, "error": str(exc)})
        return None

    async def save(self, thread_id: str, state: dict) -> None:
        """Upsert state for thread_id."""
        try:
            serialized = serialize_state(state)
            await self._collection().update_one(
                {"thread_id": thread_id},
                {"$set": {"thread_id": thread_id, "state": serialized, "updated_at": datetime.utcnow()}},
                upsert=True,
            )
            logger.info("Checkpointer: state saved", extra={"thread_id": thread_id})
        except Exception as exc:
            logger.error("Checkpointer save failed", extra={"thread_id": thread_id, "error": str(exc)})

    async def get_messages(self, thread_id: str) -> list[dict]:
        """Convenience: return only messages from saved state."""
        state = await self.load(thread_id)
        if state:
            return state.get("messages", [])
        return []


# Singleton
checkpointer = MongoCheckpointer()
