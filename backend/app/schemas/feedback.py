"""Feedback schemas."""
from pydantic import BaseModel
from typing import Literal


class FeedbackRequest(BaseModel):
    thread_id: str
    product_id: str
    action: Literal["click", "like", "ignore"]


class FeedbackResponse(BaseModel):
    success: bool
    message: str = "Feedback recorded"
