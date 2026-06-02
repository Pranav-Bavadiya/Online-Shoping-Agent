"""Razorpay payment service — test mode only."""
import hashlib
import hmac
import json
from datetime import datetime
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.db import collections as col
from app.models.payment import PaymentModel
from app.utils.uuid import new_request_id

logger = get_logger(__name__)


def _get_razorpay_client():
    try:
        import razorpay
        return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
    except ImportError:
        return None


async def create_razorpay_order(order_id: str, user_id: str, amount_inr: float, currency: str = "INR") -> dict:
    """Create a Razorpay order. Returns order details including razorpay_order_id."""
    amount_paise = int(amount_inr * 100)

    client = _get_razorpay_client()

    if not client or not settings.razorpay_key_id:
        # Graceful degradation — return a mock order for dev/test
        mock_rzp_id = f"order_test_{new_request_id()[:12]}"
        logger.warning("Razorpay not configured — using mock payment order")
        rz_order = {"id": mock_rzp_id, "amount": amount_paise, "currency": currency, "status": "created"}
    else:
        rz_order = client.order.create({
            "amount": amount_paise,
            "currency": currency,
            "receipt": order_id[:40],
            "notes": {"internal_order_id": order_id},
        })

    # Persist payment record
    payment = PaymentModel(
        _id=f"pay_{new_request_id()[:12]}",
        order_id=order_id,
        user_id=user_id,
        razorpay_order_id=rz_order["id"],
        amount=amount_paise,
        currency=currency,
        status="created",
    )
    await col.payments().insert_one(payment.to_doc())

    logger.info("Payment order created", extra={"razorpay_order_id": rz_order["id"], "order_id": order_id})
    return {
        "razorpay_order_id": rz_order["id"],
        "amount": amount_paise,
        "currency": currency,
        "key_id": settings.razorpay_key_id or "rzp_test_mock",
    }


async def verify_payment(
    razorpay_payment_id: str,
    razorpay_order_id: str,
    razorpay_signature: str,
) -> bool:
    """Verify Razorpay payment signature. Returns True if valid."""
    if not settings.razorpay_key_secret:
        # Dev mode — accept all payments
        logger.warning("Razorpay secret not set — auto-approving payment (DEV MODE)")
        await _mark_payment_captured(razorpay_order_id, razorpay_payment_id, razorpay_signature)
        return True

    expected = hmac.new(
        settings.razorpay_key_secret.encode(),
        f"{razorpay_order_id}|{razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()

    if expected != razorpay_signature:
        logger.warning("Payment signature mismatch", extra={"order": razorpay_order_id})
        await col.payments().update_one(
            {"razorpay_order_id": razorpay_order_id},
            {"$set": {"status": "failed", "updated_at": datetime.utcnow()}},
        )
        return False

    await _mark_payment_captured(razorpay_order_id, razorpay_payment_id, razorpay_signature)
    return True


async def _mark_payment_captured(
    razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str
) -> None:
    await col.payments().update_one(
        {"razorpay_order_id": razorpay_order_id},
        {
            "$set": {
                "razorpay_payment_id": razorpay_payment_id,
                "razorpay_signature": razorpay_signature,
                "status": "captured",
                "updated_at": datetime.utcnow(),
            }
        },
    )


async def get_payment_by_order(order_id: str) -> Optional[dict]:
    return await col.payments().find_one({"order_id": order_id})
