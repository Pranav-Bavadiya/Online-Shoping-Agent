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
    seller_id: Optional[str] = None  # seller who owns this item

    def to_doc(self) -> dict:
        return self.model_dump()


class SellerSubOrderModel(BaseModel):
    """A per-seller sub-order grouped under a parent order."""
    id: str = Field(alias="_id")
    parent_order_id: str           # links to the parent OrderModel
    seller_id: str
    user_id: str
    thread_id: str
    items: list[OrderItemModel]
    delivery_address: dict
    subtotal: float
    total: float
    currency: str = "INR"
    status: str = "PENDING_PAYMENT"
    razorpay_order_id: Optional[str] = None
    payment_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    model_config = {"populate_by_name": True}

    def to_doc(self) -> dict:
        return self.model_dump(by_alias=True)


class OrderModel(BaseModel):
    """Parent order — one per checkout session regardless of how many sellers."""
    id: str = Field(alias="_id")
    user_id: str
    thread_id: str
    items: list[OrderItemModel]
    delivery_address: dict
    subtotal: float
    total: float
    currency: str = "INR"
    status: str = "PENDING_PAYMENT"  # PENDING_PAYMENT | PAID | DISPATCHED | COMPLETED
    seller_sub_order_ids: list[str] = Field(default_factory=list)  # ids of SellerSubOrders
    razorpay_order_id: Optional[str] = None
    payment_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    model_config = {"populate_by_name": True}

    def to_doc(self) -> dict:
        return self.model_dump(by_alias=True)
