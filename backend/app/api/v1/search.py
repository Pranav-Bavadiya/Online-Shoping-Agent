"""Search API endpoint — single entry point for the AI agent pipeline."""
from fastapi import APIRouter, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.api.deps import get_current_user
from app.core.rate_limiter import limiter
from app.schemas.search import SearchRequest, SearchResponse
from app.services.search_service import handle_search

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
@limiter.limit("20/minute")
async def search(request: Request, body: SearchRequest, user=Depends(get_current_user)):
    result = await handle_search(
        user_id=user["_id"],
        query=body.query,
        thread_id=body.thread_id,
    )
    return SearchResponse(
        thread_id=result["thread_id"],
        content=result["content"],
        products=result.get("products", []),
        clarification_question=result.get("clarification_question"),
        cart=result.get("cart"),
        checkout=result.get("checkout"),
        selected_marketplaces=result.get("selected_marketplaces"),
    )
