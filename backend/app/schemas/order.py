"""Order schemas."""
from typing import Optional
from pydantic import BaseModel


class OrderItemResponse(BaseModel):
    product_id: str
    title: str
    price: dict
    quantity: int
    source: str
    image: str


class OrderResponse(BaseModel):
    order_id: str
    user_id: str
    thread_id: str
    items: list[OrderItemResponse]
    delivery_address: dict
    subtotal: float
    total: float
    currency: str
    status: str
    razorpay_order_id: Optional[str]
    created_at: str
