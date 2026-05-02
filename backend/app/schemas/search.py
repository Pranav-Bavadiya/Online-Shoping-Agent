"""Search request/response schemas."""
from typing import Optional
from pydantic import BaseModel
from app.schemas.product import MessageProductSchema


class SearchRequest(BaseModel):
    query: str
    thread_id: Optional[str] = None


class SearchResponse(BaseModel):
    thread_id: str
    content: str
    products: list[MessageProductSchema] = []
    clarification_question: Optional[str] = None
