"""Cart schemas."""
from typing import Optional
from pydantic import BaseModel


class AddToCartRequest(BaseModel):
    product_id: str
    quantity: int = 1


class RemoveFromCartRequest(BaseModel):
    cart_item_id: str


class UpdateCartItemRequest(BaseModel):
    cart_item_id: str
    quantity: int


class CartItemResponse(BaseModel):
    cart_item_id: str
    product_id: str
    title: str
    price: dict
    image: str
    url: str
    source: str
    can_buy_here: bool
    redirect_url: str
    quantity: int


class CartResponse(BaseModel):
    thread_id: str
    items: list[CartItemResponse]
    purchasable_count: int
    external_count: int
    estimated_total: float
