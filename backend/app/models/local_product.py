"""Local marketplace product DB model."""
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field
from app.utils.time import utcnow


class LocalProductModel(BaseModel):
    id: str = Field(alias="_id")
    seller_id: str
    title: str
    description: str = ""
    price: float
    currency: str = "INR"
    category: str = ""
    keywords: list[str] = []
    image: str = ""
    stock: int = 0
    is_active: bool = True
    attributes: dict[str, Any] = {}
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    model_config = {"populate_by_name": True}

    def to_doc(self) -> dict:
        return self.model_dump(by_alias=True)
