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

# ── Commerce collections ──────────────────────────────────────────────────────

def sellers() -> AsyncIOMotorCollection:
    return get_database()["sellers"]

def local_products() -> AsyncIOMotorCollection:
    return get_database()["local_products"]

def thread_carts() -> AsyncIOMotorCollection:
    return get_database()["thread_carts"]

def orders() -> AsyncIOMotorCollection:
    return get_database()["orders"]

def seller_sub_orders() -> AsyncIOMotorCollection:
    """Per-seller sub-orders grouped under a parent order."""
    return get_database()["seller_sub_orders"]

def payments() -> AsyncIOMotorCollection:
    return get_database()["payments"]
