"""Seller DB model."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from app.utils.time import utcnow


class SellerModel(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    shop_name: str
    description: str = ""
    is_active: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    model_config = {"populate_by_name": True}

    def to_doc(self) -> dict:
        return self.model_dump(by_alias=True)
