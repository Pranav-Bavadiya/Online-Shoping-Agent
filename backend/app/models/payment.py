"""Payment DB model — Razorpay lifecycle tracking."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from app.utils.time import utcnow


class PaymentModel(BaseModel):
    id: str = Field(alias="_id")
    order_id: str           # internal order id
    user_id: str
    razorpay_order_id: str
    razorpay_payment_id: Optional[str] = None
    razorpay_signature: Optional[str] = None
    amount: float           # in smallest unit (paise)
    currency: str = "INR"
    status: str = "created" # created | captured | failed
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    model_config = {"populate_by_name": True}

    def to_doc(self) -> dict:
        return self.model_dump(by_alias=True)
