"""Checkout REST API — frontend-driven payment flow.

Agent scope  : start_checkout → address selection → emits step="payment_required"
Frontend scope: POST /checkout/payment → Razorpay widget → POST /checkout/confirm
                POST /checkout/notify  → injects chat event (no agent run)

The agent NEVER creates Razorpay orders or confirms payments.
"""
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.core.logging import get_logger
from app.core.constants import CHECKOUT_STEP_PAYMENT, CHECKOUT_STEP_DONE
from app.db import collections as col
from app.graph.checkpointer.memory import checkpointer
from app.schemas.checkout import (
    CreatePaymentRequest,
    ConfirmPaymentRequest,
    NotifyOrderRequest,
    PaymentInitResponse,
    OrderConfirmationResponse,
    NotifyOrderResponse,
)
from app.services import cart_service, order_service, payment_service

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
    After success, frontend should call POST /checkout/notify to inject
    the confirmation event into the chat so the agent can acknowledge it.

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

    # ── Mark order paid ───────────────────────────────────────────────────────
    await order_service.mark_order_paid(order_id, body.razorpay_payment_id)

    # ── Remove purchased items from cart ──────────────────────────────────────
    # Use items stored on the order to know exactly what to remove
    order_item_ids = [item.get("product_id") for item in order.get("items", [])]
    cart = await cart_service.get_cart(thread_id, user_id)
    cart_item_ids_to_remove = [
        ci["cart_item_id"] for ci in cart.get("items", [])
        if ci.get("product_id") in order_item_ids
    ]
    if cart_item_ids_to_remove:
        await cart_service.remove_purchased_items(thread_id, cart_item_ids_to_remove)

    # ── Update persisted checkout state ──────────────────────────────────────
    saved_state = await checkpointer.load(thread_id) or {}
    checkout_state = saved_state.get("checkout") or {}
    checkout_state.update({
        "step": CHECKOUT_STEP_DONE,
        "active": False,
        "payment_status": "captured",
        "selected_cart_items": [],
    })
    saved_state["checkout"] = checkout_state
    await checkpointer.save(thread_id, saved_state)

    total = float(order.get("total", 0))
    currency = order.get("currency", "INR")
    items_count = len(order.get("items", []))

    logger.info("Payment confirmed via REST", extra={
        "order_id": order_id,
        "razorpay_payment_id": body.razorpay_payment_id,
        "user_id": user_id,
    })

    return OrderConfirmationResponse(
        order_id=order_id,
        status="paid",
        total=total,
        currency=currency,
        items_count=items_count,
        message=f"🎉 Payment confirmed! Your order {order_id} has been placed.",
    )


# ── POST /checkout/notify ─────────────────────────────────────────────────────

@router.post("/notify", response_model=NotifyOrderResponse)
async def notify_order_event(body: NotifyOrderRequest, user=Depends(get_current_user)):
    """
    Inject a payment event into the thread's conversation history.
    Does NOT run the agent — just stores a system message so the agent
    sees context on the next user turn.

    Frontend MUST call this after:
      - Payment success  (event="payment_success") → agent will celebrate on next turn
      - Payment failure  (event="payment_failed")  → agent explains options on next turn
      - Payment cancel   (event="payment_cancelled")

    The injected message has role="system" so it's visible to the agent but
    not rendered as a user bubble in the frontend chat.
    """
    user_id: str = user["_id"]
    thread_id = body.thread_id

    # Build default message text per event type
    _defaults = {
        "payment_success": (
            f"[SYSTEM: Payment was successful. Order ID: {body.order_id or 'N/A'}. "
            "The user has completed payment. Acknowledge with celebration and provide order summary.]"
        ),
        "payment_failed": (
            "[SYSTEM: Payment failed or was declined. Do NOT show technical error details. "
            "Offer to retry the payment widget or change payment method.]"
        ),
        "payment_cancelled": (
            "[SYSTEM: User cancelled the payment. Acknowledge and offer to resume checkout when ready.]"
        ),
    }
    text = body.message or _defaults.get(body.event, f"[SYSTEM: Payment event: {body.event}]")

    # Load and update saved state — inject system message into messages list
    saved_state = await checkpointer.load(thread_id) or {}
    msgs: list = list(saved_state.get("messages") or [])
    msgs.append({
        "role": "system",
        "content": text,
        "products": [],
        "external_items": [],
        "has_external": False,
    })
    saved_state["messages"] = msgs

    # On success, ensure checkout state reflects done
    if body.event == "payment_success":
        cs = dict(saved_state.get("checkout") or {})
        cs["step"] = CHECKOUT_STEP_DONE
        cs["active"] = False
        saved_state["checkout"] = cs

    await checkpointer.save(thread_id, saved_state)

    logger.info("Order event injected into thread", extra={
        "thread_id": thread_id,
        "event": body.event,
        "order_id": body.order_id,
        "user_id": user_id,
    })

    return NotifyOrderResponse(ok=True, thread_id=thread_id, event=body.event)
