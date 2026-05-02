"""Async MongoDB client (Motor)."""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongodb_uri)
        logger.info("MongoDB client created", extra={"uri": settings.mongodb_uri.split("@")[-1]})
    return _client


def get_database() -> AsyncIOMotorDatabase:
    return get_client()[settings.mongodb_db_name]


async def close_client() -> None:
    global _client
    if _client:
        _client.close()
        _client = None
        logger.info("MongoDB client closed")
