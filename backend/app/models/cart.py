"""Thread cart DB model — temporary per-thread shopping state."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from app.utils.time import utcnow


class CartItemModel(BaseModel):
    cart_item_id: str
    product_id: str
    title: str
    price: dict          # {value, currency}
    image: str = ""
    url: str = ""
    source: str = "local"
    can_buy_here: bool = True
    redirect_url: str = ""
    quantity: int = 1
    seller_id: Optional[str] = None   # populated for local products
    added_at: datetime = Field(default_factory=utcnow)

    def to_doc(self) -> dict:
        return self.model_dump()


class ThreadCartModel(BaseModel):
    id: str = Field(alias="_id")   # == thread_id
    thread_id: str
    user_id: str
    items: list[CartItemModel] = []
    updated_at: datetime = Field(default_factory=utcnow)

    model_config = {"populate_by_name": True}

    def to_doc(self) -> dict:
        d = self.model_dump(by_alias=True)
        return d
