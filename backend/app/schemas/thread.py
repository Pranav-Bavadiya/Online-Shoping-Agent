"""Thread schemas."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from app.schemas.product import ExternalItemSchema, MessageProductSchema


class MessageSchema(BaseModel):
    role: str  # user | assistant | tool
    content: str
    products: list[MessageProductSchema] = []
    external_items: list[ExternalItemSchema] = []
    has_external: bool = False


class ThreadSummaryResponse(BaseModel):
    thread_id: str
    title: str
    updated_at: datetime


class ThreadDetailResponse(BaseModel):
    thread_id: str
    messages: list[MessageSchema] = []


class RenameTitleRequest(BaseModel):
    title: str
