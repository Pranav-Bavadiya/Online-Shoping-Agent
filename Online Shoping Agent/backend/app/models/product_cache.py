"""Product cache DB model."""
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field
from app.utils.time import utcnow


class QuerySignature(BaseModel):
    category: str = ""
    keywords: list[str] = []
    source: str = "ebay"


class FiltersUsed(BaseModel):
    price_min: float = 0.0
    price_max: float = 0.0


class RawProduct(BaseModel):
    product_id: str
    source: str
    title: str
    price: dict[str, Any] = Field(default_factory=lambda: {"value": 0.0, "currency": "USD"})
    url: str = ""
    image: str = ""
    rating: float = 0.0
    category: str = ""
    raw_attributes: dict[str, Any] = {}


class ProductCacheModel(BaseModel):
    query_signature: QuerySignature
    filters_used: FiltersUsed = Field(default_factory=FiltersUsed)
    raw_results: list[RawProduct] = []
    timestamp: datetime = Field(default_factory=utcnow)

    def to_doc(self) -> dict:
        return self.model_dump()
