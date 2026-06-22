"""Checkout REST API — frontend-driven payment flow.

Agent scope  : start_checkout → address selection → emits step="payment_required"
Frontend scope: POST /checkout/payment → Razorpay widget → POST /checkout/confirm
                POST /checkout/notify  → injects chat event (no agent run)
Backend scope: POST /checkout/webhook  → Razorpay payment.captured (source of truth)

The agent NEVER creates Razorpay orders or confirms payments.

Payment finalization (mark order paid, clean cart, transition checkout state,
persist confirmation chat message) happens in exactly one place —
`checkout_finalize_service.finalize_payment_for_order()` — called by both
/checkout/confirm and the webhook handler, so neither path can drift from
the other and both are safe to run more than once for the same order.
"""
from typing import Optional
import json
from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import get_current_user
from app.core.logging import get_logger
from app.core.constants import CHECKOUT_STEP_PAYMENT
from app.db import collections as col
from app.graph.checkpointer.memory import checkpointer
from app.schemas.checkout import (
    CreatePaymentRequest,
    ConfirmPaymentRequest,
    NotifyOrderRequest,
    PaymentInitResponse,
    OrderConfirmationResponse,
    NotifyOrderResponse,
    WebhookAckResponse,
)
from app.services import cart_service, order_service, payment_service
from app.services.checkout_finalize_service import (
    build_payment_success_message,
    finalize_payment_for_order,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/checkout", tags=["checkout"])


# ── POST /checkout/payment ────────────────────────────────────────────────────

@router.post("/payment", response_model=PaymentInitResponse)
async def create_payment(body: CreatePaymentRequest, user=Depends(get_current_user)):
    """
    Create a Razorpay order for the items selected during agent checkout.

    Frontend must call this after detecting checkout.step == "payment_required"
    in the search response.  Uses the address the agent already confirmed.

    Returns Razorpay credentials — frontend opens the checkout widget with these.
    """
    user_id: str = user["_id"]
    thread_id = body.thread_id

    # ── Resolve address ───────────────────────────────────────────────────────
    address_id = body.address_id
    usr = await col.users().find_one({"_id": user_id})
    addresses = usr.get("addresses", []) if usr else []
    address = next((a for a in addresses if a["id"] == address_id), None)
    if not address:
        raise HTTPException(status_code=400, detail=f"Address '{address_id}' not found.")

    # ── Resolve purchasable items from live cart ───────────────────────────────
    cart = await cart_service.get_cart(thread_id, user_id)
    summary = cart_service.build_cart_summary(cart)
    purchasable = summary["purchasable_items"]
    if not purchasable:
        raise HTTPException(status_code=400, detail="No purchasable items in cart.")

    # Optionally filter by items the agent selected (stored in checkout state)
    saved_state = await checkpointer.load(thread_id) or {}
    checkout_state = saved_state.get("checkout") or {}
    agent_selected_ids: list[str] = checkout_state.get("selected_cart_items") or []
    if agent_selected_ids:
        filtered = [i for i in purchasable if i["cart_item_id"] in agent_selected_ids]
        if filtered:
            purchasable = filtered

    subtotal = sum(float(i["price"]["value"]) * i.get("quantity", 1) for i in purchasable)
    currency = purchasable[0]["price"].get("currency", "INR")

    # ── Create internal order ─────────────────────────────────────────────────
    order_doc = await order_service.create_order(user_id, thread_id, purchasable, address)
    order_id: str = order_doc["_id"]

    # ── Create Razorpay order ─────────────────────────────────────────────────
    rz = await payment_service.create_razorpay_order(order_id, user_id, subtotal, currency)
    await order_service.update_order_razorpay(order_id, rz["razorpay_order_id"])

    # ── Update persisted checkout state ──────────────────────────────────────
    checkout_state.update({
        "step": CHECKOUT_STEP_PAYMENT,
        "current_order_id": order_id,
        "razorpay_order_id": rz["razorpay_order_id"],
    })
    saved_state["checkout"] = checkout_state
    await checkpointer.save(thread_id, saved_state)

    logger.info("Payment order created via REST", extra={
        "order_id": order_id,
        "razorpay_order_id": rz["razorpay_order_id"],
        "thread_id": thread_id,
        "user_id": user_id,
    })

    return PaymentInitResponse(
        razorpay_order_id=rz["razorpay_order_id"],
        razorpay_key_id=rz["key_id"],
        amount=rz["amount"],
        currency=currency,
        order_id=order_id,
    )


# ── POST /checkout/confirm ────────────────────────────────────────────────────

@router.post("/confirm", response_model=OrderConfirmationResponse)
async def confirm_payment(body: ConfirmPaymentRequest, user=Depends(get_current_user)):
    """
    Verify Razorpay payment signature, mark order paid, clean up cart.

    Frontend calls this after the Razorpay widget fires paymentSuccess.

    IDEMPOTENT: safe to call more than once for the same payment (e.g. a
    network retry after a dropped response). If the order is already PAID
    — whether because this endpoint already ran, or because the webhook
    beat it to finalization — this returns the same success response
    without re-running side effects or re-persisting the chat message.

    Failed verification returns HTTP 400 — frontend should call /checkout/notify
    with event="payment_failed" and show an error state (no chat pollution).
    """
    user_id: str = user["_id"]
    thread_id = body.thread_id

    # ── Verify signature ──────────────────────────────────────────────────────
    valid = await payment_service.verify_payment(
        body.razorpay_payment_id,
        body.razorpay_order_id,
        body.razorpay_signature,
    )
    if not valid:
        logger.warning("Payment verification failed", extra={
            "razorpay_order_id": body.razorpay_order_id, "user_id": user_id
        })
        raise HTTPException(
            status_code=400,
            detail={
                "error": "payment_verification_failed",
                "message": "Payment signature verification failed. Please try again or use a different payment method.",
            }
        )

    # ── Find order ────────────────────────────────────────────────────────────
    order = await col.orders().find_one({"razorpay_order_id": body.razorpay_order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found for this payment.")
    if order.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Order does not belong to this user.")

    order_id: str = order["_id"]

    # ── Finalize (idempotent — shared with webhook path) ────────────────────
    result = await finalize_payment_for_order(
        order_id=order_id,
        razorpay_payment_id=body.razorpay_payment_id,
        source="confirm",
    )
    order = result["order"]

    total = float(order.get("total", 0))
    currency = order.get("currency", "INR")
    items_count = len(order.get("items", []))

    logger.info("Payment confirmed via REST", extra={
        "order_id": order_id,
        "razorpay_payment_id": body.razorpay_payment_id,
        "user_id": user_id,
        "already_finalized": result["already_finalized"],
    })

    return OrderConfirmationResponse(
        order_id=order_id,
        status="paid",
        total=total,
        currency=currency,
        items_count=items_count,
        message=build_payment_success_message(order_id),
    )


# ── POST /checkout/notify ─────────────────────────────────────────────────────

# Canonical, user-visible messages — MUST match what the frontend appends
# optimistically so the local UI and the persisted transcript are identical.
_EVENT_MESSAGES = {
    "payment_success": None,  # built dynamically per order_id via build_payment_success_message()
    "payment_failed": "❌ Payment failed. Please try again.",
    "payment_cancelled": "⚠️ Payment was cancelled. You can resume checkout whenever you're ready.",
}

# Hidden system event tags for future agent reasoning (not rendered in chat UI —
# frontend should filter role="system" out of the visible transcript, same as
# it already does for the legacy system-message injection this replaces).
_SYSTEM_EVENT_TAGS = {
    "payment_success": "PAYMENT_SUCCESS",
    "payment_failed": "PAYMENT_FAILED",
    "payment_cancelled": "PAYMENT_CANCELLED",
}


async def _has_existing_event_message(messages: list, event: str, order_id: Optional[str]) -> bool:
    """Dedup key is (event, order_id). For events without an order_id (e.g. a
    cancellation before any order was created), dedup is skipped — there's no
    way to reliably correlate without one, and such events also don't repeat
    the way a payment_success/payment_failed webhook+confirm race can."""
    if not order_id:
        return False
    for m in messages:
        if not isinstance(m, dict):
            continue
        meta = m.get("meta") or {}
        if meta.get("event") == event and meta.get("order_id") == order_id:
            return True
    return False


@router.post("/notify", response_model=NotifyOrderResponse)
async def notify_order_event(body: NotifyOrderRequest, user=Depends(get_current_user)):
    """
    Central event-ingestion endpoint for all checkout outcomes.

    Persists a user-visible role="assistant" chat message for every event so
    payment outcomes survive refreshes/thread switches and appear naturally
    in the conversation history — no extra user turn required to see them.

    Also persists a hidden role="system" event tag alongside it, for future
    agent reasoning (frontend should not render role="system" messages).

    IDEMPOTENT: deduped by (event, order_id) — duplicate notify calls (retry,
    double-fire, etc.) will not create duplicate assistant messages.

    For event="payment_success", this delegates to the same shared
    finalize_payment_for_order() used by /checkout/confirm and the webhook,
    so calling /checkout/notify alone (even without /checkout/confirm ever
    completing) is enough to fully finalize the order.
    """
    user_id: str = user["_id"]
    thread_id = body.thread_id
    event = body.event
    order_id = body.order_id

    if event not in _EVENT_MESSAGES:
        raise HTTPException(status_code=400, detail=f"Unsupported event '{event}'.")

    # ── payment_success: delegate to the shared finalizer ──────────────────
    # This both ensures order/cart/checkout-state are correct AND persists
    # the dedup'd assistant message — so we don't duplicate that logic here.
    if event == "payment_success":
        if not order_id:
            raise HTTPException(status_code=400, detail="order_id is required for payment_success.")
        order = await col.orders().find_one({"_id": order_id})
        if not order:
            raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found.")
        if order.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Order does not belong to this user.")
        payment = await payment_service.get_payment_by_order(order_id)
        razorpay_payment_id = (payment or {}).get("razorpay_payment_id", "")
        await finalize_payment_for_order(
            order_id=order_id, razorpay_payment_id=razorpay_payment_id, source="notify",
        )
        logger.info("Order event handled via notify (payment_success)", extra={
            "thread_id": thread_id, "order_id": order_id, "user_id": user_id,
        })
        return NotifyOrderResponse(ok=True, thread_id=thread_id, event=event)

    # ── payment_failed / payment_cancelled ──────────────────────────────────
    text = body.message or _EVENT_MESSAGES[event]
    saved_state = await checkpointer.load(thread_id) or {}
    messages: list = list(saved_state.get("messages") or [])

    if not await _has_existing_event_message(messages, event, order_id):
        messages.append({
            "role": "assistant",
            "content": text,
            "products": [],
            "external_items": [],
            "has_external": False,
            "meta": {"event": event, "order_id": order_id},
        })
        # Hidden system event tag for future agent reasoning
        messages.append({
            "role": "system",
            "content": f"[{_SYSTEM_EVENT_TAGS[event]}] order_id={order_id or 'N/A'}",
            "products": [],
            "external_items": [],
            "has_external": False,
            "meta": {"event": event, "order_id": order_id, "hidden": True},
        })
        saved_state["messages"] = messages
        await checkpointer.save(thread_id, saved_state)
        logger.info("Order event persisted via notify", extra={
            "thread_id": thread_id, "event": event, "order_id": order_id, "user_id": user_id,
        })
    else:
        logger.info("Order event already persisted — skipping duplicate", extra={
            "thread_id": thread_id, "event": event, "order_id": order_id, "user_id": user_id,
        })

    return NotifyOrderResponse(ok=True, thread_id=thread_id, event=event)


# ── POST /checkout/webhook ────────────────────────────────────────────────────

@router.post("/webhook", response_model=WebhookAckResponse)
async def razorpay_webhook(request: Request):
    """
    Razorpay webhook endpoint — the backend source of truth for payment
    completion, independent of whether the frontend ever calls /checkout/confirm.

    Configure this URL (e.g. https://yourdomain.com/api/v1/checkout/webhook)
    in the Razorpay dashboard, subscribed to the `payment.captured` event.

    No JWT auth here — Razorpay calls this server-to-server. Authenticity is
    established via the X-Razorpay-Signature header instead (HMAC over the
    raw request body using the webhook secret, NOT the API key secret).

    IDEMPOTENT: delegates to the same finalize_payment_for_order() used by
    /checkout/confirm — duplicate webhook deliveries (Razorpay retries on
    any non-2xx response) are safe no-ops once the order is already PAID.
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if not payment_service.verify_webhook_signature(raw_body, signature):
        logger.warning("Webhook signature verification failed")
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    try:
        payload = json.loads(raw_body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    event_type = payload.get("event", "")
    logger.info("Webhook received", extra={"event": event_type})

    if event_type != "payment.captured":
        # Ack anything we don't act on so Razorpay doesn't retry it forever.
        return WebhookAckResponse(ok=True, handled=False, event=event_type)

    try:
        payment_entity = payload["payload"]["payment"]["entity"]
        razorpay_payment_id = payment_entity["id"]
        razorpay_order_id = payment_entity["order_id"]
    except (KeyError, TypeError):
        logger.error("Webhook payload missing expected payment entity fields")
        raise HTTPException(status_code=400, detail="Malformed webhook payload.")

    payment_record = await payment_service.get_payment_by_razorpay_order_id(razorpay_order_id)
    if not payment_record:
        logger.error("Webhook: no payment record for razorpay_order_id", extra={
            "razorpay_order_id": razorpay_order_id,
        })
        # Ack with 200 regardless — nothing we can do, and we don't want
        # Razorpay hammering retries for an order that doesn't exist on our side.
        return WebhookAckResponse(ok=True, handled=False, event=event_type)

    order_id = payment_record["order_id"]

    # Mark the payment record captured (idempotent — plain $set)
    await payment_service.mark_payment_captured(razorpay_order_id, razorpay_payment_id, signature)

    result = await finalize_payment_for_order(
        order_id=order_id,
        razorpay_payment_id=razorpay_payment_id,
        source="webhook",
    )

    logger.info("Webhook processed", extra={
        "order_id": order_id,
        "razorpay_payment_id": razorpay_payment_id,
        "already_finalized": result["already_finalized"],
    })

    return WebhookAckResponse(ok=True, handled=True, event=event_type)
