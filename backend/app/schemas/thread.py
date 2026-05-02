"""Thread schemas."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from app.schemas.product import MessageProductSchema


class MessageSchema(BaseModel):
    role: str  # user | assistant
    content: str
    products: list[MessageProductSchema] = []


class ThreadSummaryResponse(BaseModel):
    thread_id: str
    title: str
    updated_at: datetime


class ThreadDetailResponse(BaseModel):
    thread_id: str
    messages: list[MessageSchema] = []


class RenameTitleRequest(BaseModel):
    title: str
