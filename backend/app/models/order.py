"""Global order DB model — persistent transactional history."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from app.utils.time import utcnow


class OrderItemModel(BaseModel):
    product_id: str
    title: str
    price: dict
    quantity: int
    source: str
    image: str = ""

    def to_doc(self) -> dict:
        return self.model_dump()


class OrderModel(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    thread_id: str
    items: list[OrderItemModel]
    delivery_address: dict
    subtotal: float
    total: float
    currency: str = "INR"
    status: str = "PENDING_PAYMENT"  # PENDING_PAYMENT | PAID | DISPATCHED | COMPLETED
    seller_id: Optional[str] = None
    razorpay_order_id: Optional[str] = None
    payment_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    model_config = {"populate_by_name": True}

    def to_doc(self) -> dict:
        return self.model_dump(by_alias=True)
