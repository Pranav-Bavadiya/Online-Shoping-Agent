"""Checkout schemas."""
from typing import Optional
from pydantic import BaseModel


class StartCheckoutRequest(BaseModel):
    thread_id: str
    cart_item_ids: Optional[list[str]] = None  # None = all items


class SelectAddressRequest(BaseModel):
    thread_id: str
    address_id: str


class CreatePaymentRequest(BaseModel):
    thread_id: str


class ConfirmPaymentRequest(BaseModel):
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str


class CheckoutResponse(BaseModel):
    step: str
    message: str
    order_id: Optional[str] = None
    payment_link: Optional[str] = None
    razorpay_order_id: Optional[str] = None
    razorpay_key_id: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
