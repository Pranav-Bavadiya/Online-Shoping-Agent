"""
Shared payment finalization logic — the single source of truth for what
happens when a payment is confirmed captured, whether that confirmation
arrives via:

  1. POST /checkout/confirm  (frontend, after Razorpay widget success)
  2. Razorpay webhook        (payment.captured event — backend source of truth)

Both callers MUST go through `finalize_payment_for_order()` so that:
  - order/sub-order PAID transition happens exactly once
  - cart cleanup happens exactly once
  - checkout state transitions to "done" exactly once
  - the assistant payment-confirmation chat message is persisted exactly once

This function is safe to call multiple times for the same order (idempotent) —
repeated calls (duplicate webhook delivery, frontend retry after a dropped
response, webhook arriving after confirm already ran, etc.) are no-ops beyond
the first successful finalization.
"""
from datetime import datetime
from typing import Optional

from app.core.constants import CHECKOUT_STEP_DONE, ORDER_PAID
from app.core.logging import get_logger
from app.db import collections as col
from app.graph.checkpointer.memory import checkpointer
from app.services import cart_service, order_service

logger = get_logger(__name__)

PAYMENT_SUCCESS_EVENT = "payment_success"


def build_payment_success_message(order_id: str) -> str:
    """Single canonical success message text — reused by webhook, confirm, and notify
    so the frontend-appended optimistic message and the persisted message are
    guaranteed identical (requirement: messages must match byte-for-byte)."""
    return f"🎉 Payment successful! Your order {order_id} has been placed."


async def _has_existing_success_message(messages: list, order_id: str) -> bool:
    """Check whether a payment confirmation message already exists for this order.
    Looks for our tagged metadata first (robust), falling back to a content match
    for messages that may have been written before tagging existed."""
    target_text = build_payment_success_message(order_id)
    for m in messages:
        if not isinstance(m, dict):
            continue
        meta = m.get("meta") or {}
        if meta.get("event") == PAYMENT_SUCCESS_EVENT and meta.get("order_id") == order_id:
            return True
        if m.get("role") == "assistant" and m.get("content") == target_text:
            return True
    return False


async def finalize_payment_for_order(
    order_id: str,
    razorpay_payment_id: str,
    source: str,
) -> dict:
    """
    Idempotently finalize a payment for `order_id`.

    `source` is "confirm" or "webhook" — used only for logging so we can see
    which path actually performed the finalization vs. which path found it
    already done.

    Returns:
        {
            "already_finalized": bool,   # True if order was already PAID before this call
            "order": dict,               # the (possibly already-paid) order document
        }
    """
    order = await col.orders().find_one({"_id": order_id})
    if not order:
        logger.error("finalize_payment_for_order: order not found", extra={"order_id": order_id})
        raise ValueError(f"Order '{order_id}' not found")

    already_paid = order.get("status") == ORDER_PAID
    thread_id = order.get("thread_id", "")

    if already_paid:
        logger.info(
            "finalize_payment_for_order: order already PAID, skipping side effects",
            extra={"order_id": order_id, "source": source},
        )
    else:
        # ── 1. Mark order + sub-orders PAID ─────────────────────────────────
        await order_service.mark_order_paid(order_id, razorpay_payment_id)

        # ── 2. Remove purchased items from cart ─────────────────────────────
        order_item_ids = [item.get("product_id") for item in order.get("items", [])]
        user_id = order.get("user_id", "")
        if thread_id and user_id:
            cart = await cart_service.get_cart(thread_id, user_id)
            cart_item_ids_to_remove = [
                ci["cart_item_id"] for ci in cart.get("items", [])
                if ci.get("product_id") in order_item_ids
            ]
            if cart_item_ids_to_remove:
                await cart_service.remove_purchased_items(thread_id, cart_item_ids_to_remove)

        logger.info(
            "finalize_payment_for_order: order finalized",
            extra={"order_id": order_id, "source": source},
        )

    # ── 3. Update checkout state + persist confirmation message ────────────
    # Always run this step even if already_paid, because the order being PAID
    # and the checkout-state/chat-message being updated can be out of sync
    # (e.g. webhook marked the order paid but the user's browser crashed
    # before /checkout/confirm or /checkout/notify ever ran). This is exactly
    # the reconciliation scenario requirement #12 describes.
    if thread_id:
        await _sync_checkout_state_and_message(thread_id, order_id)

    # Re-fetch to return the latest doc
    order = await col.orders().find_one({"_id": order_id})
    return {"already_finalized": already_paid, "order": order}


async def _sync_checkout_state_and_message(thread_id: str, order_id: str) -> None:
    """Bring checkout.step to 'done' and ensure the assistant confirmation
    message exists exactly once. Safe to call repeatedly."""
    saved_state = await checkpointer.load(thread_id) or {}

    # ── Checkout state → done ───────────────────────────────────────────────
    checkout_state = dict(saved_state.get("checkout") or {})
    state_changed = False
    if checkout_state.get("step") != CHECKOUT_STEP_DONE:
        checkout_state.update({
            "step": CHECKOUT_STEP_DONE,
            "active": False,
            "payment_status": "captured",
            "selected_cart_items": [],
            "current_order_id": order_id,
        })
        saved_state["checkout"] = checkout_state
        state_changed = True

    # ── Persist assistant confirmation message (deduped) ───────────────────
    messages: list = list(saved_state.get("messages") or [])
    msg_added = False
    if not await _has_existing_success_message(messages, order_id):
        messages.append({
            "role": "assistant",
            "content": build_payment_success_message(order_id),
            "products": [],
            "external_items": [],
            "has_external": False,
            "meta": {"event": PAYMENT_SUCCESS_EVENT, "order_id": order_id},
        })
        saved_state["messages"] = messages
        msg_added = True

    if state_changed or msg_added:
        await checkpointer.save(thread_id, saved_state)
        logger.info(
            "Checkout state/message reconciled",
            extra={"thread_id": thread_id, "order_id": order_id,
                   "state_changed": state_changed, "message_added": msg_added},
        )
