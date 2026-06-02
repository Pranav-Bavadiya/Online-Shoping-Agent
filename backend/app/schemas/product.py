"""Product-related Pydantic schemas (API layer)."""
from typing import Any, Optional
from pydantic import BaseModel


class PriceSchema(BaseModel):
    value: float
    currency: str = "INR"


class MessageProductSchema(BaseModel):
    """Product returned inside chat messages — includes commerce metadata."""
    product_id: str
    title: str
    price: PriceSchema
    image: str = ""
    url: str = ""
    rating: float = 0.0
    source: str = ""
    short_reason: str = ""
    # Commerce fields
    can_buy_here: bool = False
    redirect_url: str = ""
    cart_supported: bool = False


class RawProductSchema(BaseModel):
    """Full product stored in cache."""
    product_id: str
    source: str
    title: str
    price: PriceSchema
    url: str = ""
    image: str = ""
    rating: float = 0.0
    category: str = ""
    raw_attributes: dict[str, Any] = {}
    can_buy_here: bool = False
    redirect_url: str = ""
    cart_supported: bool = False
