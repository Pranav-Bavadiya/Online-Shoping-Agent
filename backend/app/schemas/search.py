"""Search request/response schemas."""
from typing import Optional
from pydantic import BaseModel
from app.schemas.product import MessageProductSchema, ExternalItemSchema


class SearchRequest(BaseModel):
    query: str
    thread_id: Optional[str] = None


class SearchResponse(BaseModel):
    thread_id: str
    content: str
    products: list[MessageProductSchema] = []
    external_items: list[ExternalItemSchema] = []   # external/redirect-only items
    has_external: bool = False
    clarification_question: Optional[str] = None
    # Commerce state returned per-response
    cart: Optional[dict] = None
    checkout: Optional[dict] = None
    selected_marketplaces: Optional[list[str]] = None
