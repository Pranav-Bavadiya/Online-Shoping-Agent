"""Search endpoint — the core pipeline trigger."""
from fastapi import APIRouter, Depends, Request

from app.api.deps import get_current_user_id
from app.core.rate_limiter import SEARCH_RATE, limiter
from app.core.logging import get_logger
from app.schemas.search import SearchRequest, SearchResponse
from app.services.search_service import handle_search

logger = get_logger(__name__)
router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
@limiter.limit(SEARCH_RATE)
async def search(
    request: Request,          # required by slowapi
    body: SearchRequest,
    user_id: str = Depends(get_current_user_id),
):
    request_id = getattr(request.state, "request_id", "-")
    logger.info("POST /search", extra={
        "user_id": user_id,
        "thread_id": body.thread_id,
        "request_id": request_id,
    })

    result = await handle_search(
        user_id=user_id,
        query=body.query,
        thread_id=body.thread_id,
    )

    return SearchResponse(
        thread_id=result["thread_id"],
        content=result["content"],
        products=result.get("products") or [],
        clarification_question=result.get("clarification_question"),
    )
