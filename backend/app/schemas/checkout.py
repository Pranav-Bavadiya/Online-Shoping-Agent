"""Checkout schemas — REST API layer for frontend-driven payment flow."""
from typing import Optional
from pydantic import BaseModel


# ── Request schemas ───────────────────────────────────────────────────────────

class CreatePaymentRequest(BaseModel):
    """
    Frontend calls POST /checkout/payment after detecting checkout.step=="payment_required".
    thread_id and address_id come from the checkout state the agent already set.
    """
    thread_id: str
    address_id: str   # from checkout.selected_address_id (agent already confirmed this)


class ConfirmPaymentRequest(BaseModel):
    """
    Frontend calls POST /checkout/confirm after Razorpay widget succeeds.
    All three Razorpay fields are required for signature verification.
    """
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str
    thread_id: str    # needed to remove purchased items from cart


class NotifyOrderRequest(BaseModel):
    """
    Frontend calls POST /checkout/notify to inject a system event into
    conversation history after payment success/failure.
    This does NOT run the agent — it only stores a message.
    """
    thread_id: str
    event: str            # "payment_success" | "payment_failed" | "payment_cancelled"
    order_id: Optional[str] = None
    message: Optional[str] = None   # optional override; backend builds default if absent


# ── Response schemas ──────────────────────────────────────────────────────────

class PaymentInitResponse(BaseModel):
    """Returned by POST /checkout/payment — everything the frontend needs to open Razorpay."""
    razorpay_order_id: str
    razorpay_key_id: str
    amount: float          # in smallest currency unit (paise for INR)
    currency: str
    order_id: str          # internal order ID


class OrderConfirmationResponse(BaseModel):
    """Returned by POST /checkout/confirm — full order confirmation payload."""
    order_id: str
    status: str            # "paid"
    total: float
    currency: str
    items_count: int
    message: str           # "🎉 Payment confirmed! Your order has been placed."


class NotifyOrderResponse(BaseModel):
    """Returned by POST /checkout/notify."""
    ok: bool
    thread_id: str
    event: str
