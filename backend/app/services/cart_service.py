"""Thread-scoped cart service."""
from datetime import datetime
from typing import Optional

from app.core.logging import get_logger
from app.db import collections as col
from app.models.cart import CartItemModel, ThreadCartModel
from app.utils.uuid import new_request_id

logger = get_logger(__name__)


async def _get_or_create_cart(thread_id: str, user_id: str) -> dict:
    doc = await col.thread_carts().find_one({"thread_id": thread_id})
    if not doc:
        cart = ThreadCartModel(
            _id=thread_id, thread_id=thread_id, user_id=user_id, items=[]
        )
        await col.thread_carts().insert_one(cart.to_doc())
        doc = cart.to_doc()
    return doc


async def get_cart(thread_id: str, user_id: str) -> dict:
    return await _get_or_create_cart(thread_id, user_id)


async def add_item(thread_id: str, user_id: str, product: dict, quantity: int = 1) -> dict:
    """Add or increment a product in the cart. Returns updated cart."""
    cart = await _get_or_create_cart(thread_id, user_id)
    items: list[dict] = cart.get("items", [])

    # Check if already in cart
    for item in items:
        if item["product_id"] == product["product_id"]:
            item["quantity"] = min(item["quantity"] + quantity, 99)
            await col.thread_carts().update_one(
                {"thread_id": thread_id},
                {"$set": {"items": items, "updated_at": datetime.utcnow()}},
            )
            logger.info("Cart: incremented item", extra={"product_id": product["product_id"]})
            return await get_cart(thread_id, user_id)

    # Add new item
    source = product.get("source", "local")
    can_buy_here = source == "local"
    new_item = CartItemModel(
        cart_item_id=f"ci_{new_request_id()[:8]}",
        product_id=product["product_id"],
        title=product.get("title", ""),
        price=product.get("price", {"value": 0, "currency": "INR"}),
        image=product.get("image", ""),
        url=product.get("url", ""),
        source=source,
        can_buy_here=product.get("can_buy_here", can_buy_here),
        redirect_url=product.get("url", ""),
        quantity=quantity,
    )
    items.append(new_item.to_doc())
    await col.thread_carts().update_one(
        {"thread_id": thread_id},
        {"$set": {"items": items, "updated_at": datetime.utcnow()}},
        upsert=True,
    )
    logger.info("Cart: added item", extra={"product_id": product["product_id"], "thread_id": thread_id})
    return await get_cart(thread_id, user_id)


async def remove_item(thread_id: str, cart_item_id: str) -> dict:
    cart = await col.thread_carts().find_one({"thread_id": thread_id})
    if not cart:
        return {"items": []}
    items = [i for i in cart.get("items", []) if i["cart_item_id"] != cart_item_id]
    await col.thread_carts().update_one(
        {"thread_id": thread_id},
        {"$set": {"items": items, "updated_at": datetime.utcnow()}},
    )
    return await get_cart(thread_id, cart["user_id"])


async def update_quantity(thread_id: str, cart_item_id: str, quantity: int) -> dict:
    cart = await col.thread_carts().find_one({"thread_id": thread_id})
    if not cart:
        return {"items": []}
    items = cart.get("items", [])
    if quantity <= 0:
        items = [i for i in items if i["cart_item_id"] != cart_item_id]
    else:
        for item in items:
            if item["cart_item_id"] == cart_item_id:
                item["quantity"] = min(quantity, 99)
    await col.thread_carts().update_one(
        {"thread_id": thread_id},
        {"$set": {"items": items, "updated_at": datetime.utcnow()}},
    )
    return await get_cart(thread_id, cart["user_id"])


async def clear_cart(thread_id: str) -> None:
    await col.thread_carts().update_one(
        {"thread_id": thread_id},
        {"$set": {"items": [], "updated_at": datetime.utcnow()}},
    )


async def remove_purchased_items(thread_id: str, cart_item_ids: list[str]) -> None:
    """Remove only the purchased items, keeping the rest intact."""
    cart = await col.thread_carts().find_one({"thread_id": thread_id})
    if not cart:
        return
    remaining = [i for i in cart.get("items", []) if i["cart_item_id"] not in cart_item_ids]
    await col.thread_carts().update_one(
        {"thread_id": thread_id},
        {"$set": {"items": remaining, "updated_at": datetime.utcnow()}},
    )
    logger.info("Cart: removed purchased items", extra={
        "thread_id": thread_id, "removed": len(cart_item_ids), "remaining": len(remaining)
    })


def build_cart_summary(cart: dict) -> dict:
    items = cart.get("items", [])
    purchasable = [i for i in items if i.get("can_buy_here")]
    external = [i for i in items if not i.get("can_buy_here")]
    total = sum(
        float(i.get("price", {}).get("value", 0)) * i.get("quantity", 1)
        for i in purchasable
    )
    return {
        "items": items,
        "purchasable_count": len(purchasable),
        "external_count": len(external),
        "estimated_total": round(total, 2),
        "purchasable_items": purchasable,
        "external_items": external,
    }
