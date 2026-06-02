"""Checkout REST API — used by frontend to mirror tool-loop checkout state."""
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.schemas.checkout import (
    CheckoutResponse, ConfirmPaymentRequest, CreatePaymentRequest,
    SelectAddressRequest, StartCheckoutRequest,
)
from app.services import cart_service, order_service, payment_service

router = APIRouter(prefix="/checkout", tags=["checkout"])


@router.post("/start", response_model=CheckoutResponse)
async def start_checkout(body: StartCheckoutRequest, user=Depends(get_current_user)):
    from app.graph.nodes.tools.checkout_tools import start_checkout_tool
    result = await start_checkout_tool(body.thread_id, user["_id"], body.cart_item_ids)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return CheckoutResponse(step=result.get("step", "init"), message=result["message"])


@router.post("/address", response_model=CheckoutResponse)
async def select_address(body: SelectAddressRequest, user=Depends(get_current_user)):
    from app.graph.nodes.tools.checkout_tools import select_address_tool
    result = await select_address_tool(user["_id"], body.address_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return CheckoutResponse(step=result.get("step", "address_selected"), message=result["message"])


@router.post("/payment", response_model=CheckoutResponse)
async def create_payment(body: CreatePaymentRequest, user=Depends(get_current_user)):
    """Create a Razorpay payment order. Frontend uses returned details for Razorpay checkout."""
    from app.services.cart_service import get_cart, build_cart_summary
    cart = await get_cart(body.thread_id, user["_id"])
    summary = build_cart_summary(cart)
    purchasable = summary["purchasable_items"]
    if not purchasable:
        raise HTTPException(status_code=400, detail="No purchasable items in cart")

    # Use most recent address
    from app.db import collections as col
    usr = await col.users().find_one({"_id": user["_id"]})
    addresses = usr.get("addresses", []) if usr else []
    if not addresses:
        raise HTTPException(status_code=400, detail="Please add a delivery address first")
    address = addresses[-1]

    ids = [i["cart_item_id"] for i in purchasable]
    from app.graph.nodes.tools.checkout_tools import create_payment_tool
    result = await create_payment_tool(body.thread_id, user["_id"], ids, address)
    if result.get("status") != "success":
        raise HTTPException(status_code=500, detail=result.get("message", "Payment creation failed"))

    return CheckoutResponse(
        step=result["step"], message=result["message"],
        order_id=result.get("order_id"),
        razorpay_order_id=result.get("razorpay_order_id"),
        razorpay_key_id=result.get("razorpay_key_id"),
        amount=result.get("amount"),
        currency=result.get("currency"),
    )


@router.post("/confirm", response_model=CheckoutResponse)
async def confirm_payment(body: ConfirmPaymentRequest, user=Depends(get_current_user)):
    valid = await payment_service.verify_payment(
        body.razorpay_payment_id, body.razorpay_order_id, body.razorpay_signature
    )
    if not valid:
        raise HTTPException(status_code=400, detail="Payment verification failed")
    order = await order_service.get_order(
        (await payment_service.get_payment_by_order(body.razorpay_order_id) or {}).get("order_id", "")
    )
    await order_service.mark_order_paid(order["_id"], body.razorpay_payment_id)
    return CheckoutResponse(
        step="done",
        message=f"Payment confirmed! Order {order['_id']} is now being processed.",
        order_id=order["_id"],
    )
