"""Seller schemas."""
from typing import Optional
from pydantic import BaseModel


class SellerRegisterRequest(BaseModel):
    shop_name: str
    description: str = ""


class SellerProfileUpdateRequest(BaseModel):
    shop_name: Optional[str] = None
    description: Optional[str] = None


class SellerProfileResponse(BaseModel):
    seller_id: str
    shop_name: str
    description: str
    is_active: bool


class LocalProductCreateRequest(BaseModel):
    title: str
    description: str = ""
    price: float
    currency: str = "INR"
    category: str = ""
    keywords: list[str] = []
    image: str = ""
    stock: int = 0
    attributes: dict = {}


class LocalProductUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    category: Optional[str] = None
    keywords: Optional[list[str]] = None
    image: Optional[str] = None
    stock: Optional[int] = None
    attributes: Optional[dict] = None
    is_active: Optional[bool] = None


class LocalProductResponse(BaseModel):
    product_id: str
    seller_id: str
    title: str
    description: str
    price: float
    currency: str
    category: str
    keywords: list[str]
    image: str
    stock: int
    is_active: bool
    attributes: dict


class SellerOrderResponse(BaseModel):
    order_id: str
    user_id: str
    status: str
    items: list[dict]
    total: float
    currency: str
    delivery_address: dict
    created_at: str


class SellerDashboardSummary(BaseModel):
    total_products: int
    active_products: int
    active_orders: int
    pending_dispatches: int
