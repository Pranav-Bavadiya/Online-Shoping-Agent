"""User DB model (Pydantic v2)."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from app.utils.time import utcnow


class Address(BaseModel):
    id: str
    line1: str
    line2: str = ""
    city: str
    state: str
    pincode: str
    country: str = "India"


class UserModel(BaseModel):
    id: str = Field(alias="_id")
    name: str
    email: EmailStr
    password_hash: Optional[str] = None
    google_id: Optional[str] = None
    phone: Optional[str] = None
    addresses: list[Address] = []
    default_address_id: Optional[str] = None
    profile_completed: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    model_config = {"populate_by_name": True}

    def to_doc(self) -> dict:
        d = self.model_dump(by_alias=True)
        return d
