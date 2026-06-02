"""Global order service — persistent transactional history."""
from datetime import datetime
from typing import Optional

from app.core.constants import (
    ACTIVE_ORDER_STATUSES, ORDER_DISPATCHED, ORDER_PAID,
    ORDER_PENDING_PAYMENT
)
from app.core.logging import get_logger
from app.db import collections as col
from app.models.order import OrderItemModel, OrderModel
from app.utils.uuid import new_request_id

logger = get_logger(__name__)


async def create_order(
    user_id: str,
    thread_id: str,
    cart_items: list[dict],
    delivery_address: dict,
    razorpay_order_id: Optional[str] = None,
) -> dict:
    """Create an order from selected cart items."""
    items = [
        OrderItemModel(
            product_id=ci["product_id"],
            title=ci.get("title", ""),
            price=ci.get("price", {"value": 0, "currency": "INR"}),
            quantity=ci.get("quantity", 1),
            source=ci.get("source", "local"),
            image=ci.get("image", ""),
        )
        for ci in cart_items
    ]
    subtotal = sum(
        float(i.price["value"]) * i.quantity for i in items
    )
    order = OrderModel(
        _id=f"ord_{new_request_id()[:12]}",
        user_id=user_id,
        thread_id=thread_id,
        items=items,
        delivery_address=delivery_address,
        subtotal=round(subtotal, 2),
        total=round(subtotal, 2),
        currency=cart_items[0].get("price", {}).get("currency", "INR") if cart_items else "INR",
        status=ORDER_PENDING_PAYMENT,
        razorpay_order_id=razorpay_order_id,
    )
    await col.orders().insert_one(order.to_doc())
    logger.info("Order created", extra={"order_id": order.id, "user_id": user_id})
    return order.to_doc()


async def mark_order_paid(order_id: str, razorpay_payment_id: str) -> None:
    await col.orders().update_one(
        {"_id": order_id},
        {"$set": {"status": ORDER_PAID, "payment_id": razorpay_payment_id, "updated_at": datetime.utcnow()}},
    )
    logger.info("Order marked PAID", extra={"order_id": order_id})


async def dispatch_order(order_id: str, seller_id: str) -> dict:
    """Seller dispatches the order."""
    order = await col.orders().find_one({"_id": order_id})
    if not order:
        raise ValueError(f"Order {order_id} not found")
    if order.get("status") != ORDER_PAID:
        raise ValueError(f"Order {order_id} is not in PAID status (current: {order.get('status')})")
    await col.orders().update_one(
        {"_id": order_id},
        {"$set": {"status": ORDER_DISPATCHED, "updated_at": datetime.utcnow()}},
    )
    logger.info("Order dispatched", extra={"order_id": order_id, "seller_id": seller_id})
    return await col.orders().find_one({"_id": order_id})


async def get_user_orders(user_id: str, active_only: bool = False) -> list[dict]:
    query: dict = {"user_id": user_id}
    if active_only:
        query["status"] = {"$in": ACTIVE_ORDER_STATUSES}
    cursor = col.orders().find(query).sort("created_at", -1)
    return await cursor.to_list(length=200)


async def get_order(order_id: str) -> Optional[dict]:
    return await col.orders().find_one({"_id": order_id})


async def get_seller_orders(seller_id: str, active_only: bool = True) -> list[dict]:
    query: dict = {"seller_id": seller_id}
    if active_only:
        query["status"] = {"$in": ACTIVE_ORDER_STATUSES}
    cursor = col.orders().find(query).sort("created_at", -1)
    return await cursor.to_list(length=200)


async def update_order_razorpay(order_id: str, razorpay_order_id: str) -> None:
    await col.orders().update_one(
        {"_id": order_id},
        {"$set": {"razorpay_order_id": razorpay_order_id, "updated_at": datetime.utcnow()}},
    )
