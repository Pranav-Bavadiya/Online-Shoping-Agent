"""Global order service — persistent transactional history.

Orders are split seller-wise: one SellerSubOrder per seller, all grouped under
a parent OrderModel. Payment is taken on the parent order; when payment is
confirmed all sub-orders are marked PAID so each seller can see their own orders.
"""
from collections import defaultdict
from datetime import datetime
from typing import Optional

from app.core.constants import (
    ACTIVE_ORDER_STATUSES, ORDER_DISPATCHED, ORDER_PAID,
    ORDER_PENDING_PAYMENT
)
from app.core.logging import get_logger
from app.db import collections as col
from app.models.order import OrderItemModel, OrderModel, SellerSubOrderModel
from app.utils.uuid import new_request_id

logger = get_logger(__name__)

_FALLBACK_SELLER = "unknown_seller"


async def create_order(
    user_id: str,
    thread_id: str,
    cart_items: list[dict],
    delivery_address: dict,
    razorpay_order_id: Optional[str] = None,
) -> dict:
    """Create a parent order and per-seller sub-orders from selected cart items."""

    # Build OrderItemModels, pulling seller_id from the cart item
    items = [
        OrderItemModel(
            product_id=ci["product_id"],
            title=ci.get("title", ""),
            price=ci.get("price", {"value": 0, "currency": "INR"}),
            quantity=ci.get("quantity", 1),
            source=ci.get("source", "local"),
            image=ci.get("image", ""),
            seller_id=ci.get("seller_id") or _FALLBACK_SELLER,
        )
        for ci in cart_items
    ]

    subtotal = sum(float(i.price["value"]) * i.quantity for i in items)
    currency = cart_items[0].get("price", {}).get("currency", "INR") if cart_items else "INR"
    parent_id = f"ord_{new_request_id()[:12]}"

    # ── Create per-seller sub-orders ──────────────────────────────────────────
    seller_groups: dict[str, list[OrderItemModel]] = defaultdict(list)
    for item in items:
        seller_groups[item.seller_id or _FALLBACK_SELLER].append(item)

    sub_order_ids: list[str] = []
    for seller_id, seller_items in seller_groups.items():
        seller_subtotal = sum(float(i.price["value"]) * i.quantity for i in seller_items)
        sub = SellerSubOrderModel(
            _id=f"so_{new_request_id()[:12]}",
            parent_order_id=parent_id,
            seller_id=seller_id,
            user_id=user_id,
            thread_id=thread_id,
            items=seller_items,
            delivery_address=delivery_address,
            subtotal=round(seller_subtotal, 2),
            total=round(seller_subtotal, 2),
            currency=currency,
            status=ORDER_PENDING_PAYMENT,
            razorpay_order_id=razorpay_order_id,
        )
        await col.seller_sub_orders().insert_one(sub.to_doc())
        sub_order_ids.append(sub.id)
        logger.info("Sub-order created", extra={"sub_order_id": sub.id, "seller_id": seller_id})

    # ── Create parent order ───────────────────────────────────────────────────
    order = OrderModel(
        _id=parent_id,
        user_id=user_id,
        thread_id=thread_id,
        items=items,
        delivery_address=delivery_address,
        subtotal=round(subtotal, 2),
        total=round(subtotal, 2),
        currency=currency,
        status=ORDER_PENDING_PAYMENT,
        seller_sub_order_ids=sub_order_ids,
        razorpay_order_id=razorpay_order_id,
    )
    await col.orders().insert_one(order.to_doc())
    logger.info("Parent order created", extra={"order_id": order.id, "sub_orders": len(sub_order_ids)})
    return order.to_doc()


async def mark_order_paid(order_id: str, razorpay_payment_id: str) -> None:
    """Mark parent order and all its sub-orders as PAID."""
    now = datetime.utcnow()
    await col.orders().update_one(
        {"_id": order_id},
        {"$set": {"status": ORDER_PAID, "payment_id": razorpay_payment_id, "updated_at": now}},
    )
    # Propagate PAID status to all seller sub-orders
    await col.seller_sub_orders().update_many(
        {"parent_order_id": order_id},
        {"$set": {"status": ORDER_PAID, "payment_id": razorpay_payment_id, "updated_at": now}},
    )
    logger.info("Order and sub-orders marked PAID", extra={"order_id": order_id})


async def dispatch_order(order_id: str, seller_id: str) -> dict:
    """Seller dispatches their sub-order."""
    # Find the sub-order for this seller under this parent order
    sub = await col.seller_sub_orders().find_one(
        {"parent_order_id": order_id, "seller_id": seller_id}
    )
    # Fallback: maybe order_id IS a sub-order id already
    if not sub:
        sub = await col.seller_sub_orders().find_one({"_id": order_id, "seller_id": seller_id})
    if not sub:
        raise ValueError(f"No sub-order found for seller {seller_id} in order {order_id}")
    if sub.get("status") != ORDER_PAID:
        raise ValueError(f"Sub-order is not in PAID status (current: {sub.get('status')})")

    await col.seller_sub_orders().update_one(
        {"_id": sub["_id"]},
        {"$set": {"status": ORDER_DISPATCHED, "updated_at": datetime.utcnow()}},
    )
    logger.info("Sub-order dispatched", extra={"sub_order_id": sub["_id"], "seller_id": seller_id})
    return await col.seller_sub_orders().find_one({"_id": sub["_id"]})


async def get_user_orders(user_id: str, active_only: bool = False) -> list[dict]:
    query: dict = {"user_id": user_id}
    if active_only:
        query["status"] = {"$in": ACTIVE_ORDER_STATUSES}
    cursor = col.orders().find(query).sort("created_at", -1)
    return await cursor.to_list(length=200)


async def get_order(order_id: str) -> Optional[dict]:
    order = await col.orders().find_one({"_id": order_id})
    if order:
        # Attach sub-orders for full detail
        subs = await col.seller_sub_orders().find(
            {"parent_order_id": order_id}
        ).to_list(length=100)
        order["seller_sub_orders"] = subs
    return order


async def get_seller_orders(seller_id: str, active_only: bool = True) -> list[dict]:
    """Return sub-orders for a specific seller."""
    query: dict = {"seller_id": seller_id}
    if active_only:
        query["status"] = {"$in": ACTIVE_ORDER_STATUSES}
    cursor = col.seller_sub_orders().find(query).sort("created_at", -1)
    return await cursor.to_list(length=200)


async def update_order_razorpay(order_id: str, razorpay_order_id: str) -> None:
    now = datetime.utcnow()
    await col.orders().update_one(
        {"_id": order_id},
        {"$set": {"razorpay_order_id": razorpay_order_id, "updated_at": now}},
    )
    await col.seller_sub_orders().update_many(
        {"parent_order_id": order_id},
        {"$set": {"razorpay_order_id": razorpay_order_id, "updated_at": now}},
    )
