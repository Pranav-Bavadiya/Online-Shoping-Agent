"""Thread DB model."""
from datetime import datetime
from pydantic import BaseModel, Field
from app.utils.time import utcnow


class ThreadModel(BaseModel):
    id: str = Field(alias="_id")
    thread_id: str
    user_id: str
    title: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    is_deleted: bool = False

    model_config = {"populate_by_name": True}

    def to_doc(self) -> dict:
        return self.model_dump(by_alias=True)
