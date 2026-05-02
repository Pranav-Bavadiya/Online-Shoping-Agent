"""Typed collection accessors."""
from motor.motor_asyncio import AsyncIOMotorCollection

from app.db.client import get_database


def users() -> AsyncIOMotorCollection:
    return get_database()["users"]


def threads() -> AsyncIOMotorCollection:
    return get_database()["threads"]


def product_cache() -> AsyncIOMotorCollection:
    return get_database()["product_cache"]


def product_lookup_map() -> AsyncIOMotorCollection:
    return get_database()["product_lookup_map"]


def feedback() -> AsyncIOMotorCollection:
    return get_database()["feedback"]
