"""Seller onboarding + product management service."""
from datetime import datetime
from typing import Optional

from app.core.logging import get_logger
from app.db import collections as col
from app.models.local_product import LocalProductModel
from app.models.seller import SellerModel
from app.utils.uuid import new_request_id

logger = get_logger(__name__)


async def register_seller(user_id: str, shop_name: str, description: str = "") -> dict:
    existing = await col.sellers().find_one({"user_id": user_id})
    if existing:
        raise ValueError("User is already a seller")

    seller = SellerModel(
        _id=f"sel_{new_request_id()[:12]}",
        user_id=user_id,
        shop_name=shop_name,
        description=description,
    )
    await col.sellers().insert_one(seller.to_doc())
    # Update user role
    await col.users().update_one(
        {"_id": user_id},
        {"$set": {"role": "seller", "seller_id": seller.id, "updated_at": datetime.utcnow()}},
    )
    logger.info("Seller registered", extra={"seller_id": seller.id, "user_id": user_id})
    return seller.to_doc()


async def get_seller_by_user(user_id: str) -> Optional[dict]:
    return await col.sellers().find_one({"user_id": user_id})


async def get_seller_by_id(seller_id: str) -> Optional[dict]:
    return await col.sellers().find_one({"_id": seller_id})


async def update_seller_profile(user_id: str, updates: dict) -> dict:
    """Update shop_name/description for the seller linked to user_id."""
    seller = await get_seller_by_user(user_id)
    if not seller:
        raise ValueError("Seller profile not found")
    clean = {k: v for k, v in updates.items() if v is not None}
    if clean:
        clean["updated_at"] = datetime.utcnow()
        await col.sellers().update_one({"_id": seller["_id"]}, {"$set": clean})
    return await get_seller_by_id(seller["_id"])


# ── Product management ────────────────────────────────────────────────────────

async def create_product(seller_id: str, data: dict) -> dict:
    product = LocalProductModel(
        _id=f"lp_{new_request_id()[:12]}",
        seller_id=seller_id,
        **data,
    )
    await col.local_products().insert_one(product.to_doc())
    logger.info("Local product created", extra={"product_id": product.id, "seller_id": seller_id})
    return _product_to_response(product.to_doc())


async def get_seller_products(seller_id: str) -> list[dict]:
    cursor = col.local_products().find({"seller_id": seller_id}).sort("created_at", -1)
    docs = await cursor.to_list(length=500)
    return [_product_to_response(d) for d in docs]


async def get_product(product_doc_id: str) -> Optional[dict]:
    doc = await col.local_products().find_one({"_id": product_doc_id})
    return _product_to_response(doc) if doc else None


async def update_product(product_doc_id: str, seller_id: str, updates: dict) -> dict:
    # Security: ensure product belongs to seller
    doc = await col.local_products().find_one({"_id": product_doc_id, "seller_id": seller_id})
    if not doc:
        raise ValueError("Product not found or access denied")
    clean = {k: v for k, v in updates.items() if v is not None}
    clean["updated_at"] = datetime.utcnow()
    await col.local_products().update_one({"_id": product_doc_id}, {"$set": clean})
    updated = await col.local_products().find_one({"_id": product_doc_id})
    return _product_to_response(updated)


async def delete_product(product_doc_id: str, seller_id: str) -> None:
    doc = await col.local_products().find_one({"_id": product_doc_id, "seller_id": seller_id})
    if not doc:
        raise ValueError("Product not found or access denied")
    await col.local_products().update_one(
        {"_id": product_doc_id},
        {"$set": {"is_active": False, "updated_at": datetime.utcnow()}},
    )


def _product_to_response(doc: dict) -> dict:
    return {
        "product_id": f"local_{doc['_id']}",
        "seller_id": doc.get("seller_id", ""),
        "title": doc.get("title", ""),
        "description": doc.get("description", ""),
        "price": float(doc.get("price", 0)),
        "currency": doc.get("currency", "INR"),
        "category": doc.get("category", ""),
        "keywords": doc.get("keywords", []),
        "image": doc.get("image", ""),
        "stock": doc.get("stock", 0),
        "is_active": doc.get("is_active", True),
        "attributes": doc.get("attributes", {}),
        "_doc_id": str(doc["_id"]),
    }
