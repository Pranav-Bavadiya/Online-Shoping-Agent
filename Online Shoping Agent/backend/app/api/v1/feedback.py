"""Feedback endpoint — record user interactions with products."""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user_id
from app.schemas.feedback import FeedbackRequest, FeedbackResponse
from app.services.feedback_service import record_feedback

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", response_model=FeedbackResponse, status_code=201)
async def post_feedback(
    body: FeedbackRequest,
    user_id: str = Depends(get_current_user_id),
):
    await record_feedback(
        user_id=user_id,
        thread_id=body.thread_id,
        product_id=body.product_id,
        action=body.action,
    )
    return FeedbackResponse(success=True)
