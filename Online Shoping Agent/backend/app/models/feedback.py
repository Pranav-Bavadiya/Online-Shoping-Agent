"""Feedback DB model."""
from datetime import datetime
from pydantic import BaseModel, Field
from app.utils.time import utcnow


class FeedbackModel(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    thread_id: str
    product_id: str
    action: str  # click | like | ignore
    timestamp: datetime = Field(default_factory=utcnow)

    model_config = {"populate_by_name": True}

    def to_doc(self) -> dict:
        return self.model_dump(by_alias=True)
