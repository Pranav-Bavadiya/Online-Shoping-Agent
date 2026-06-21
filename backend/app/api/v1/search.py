"""Search API endpoint — single entry point for the AI agent pipeline."""
from fastapi import APIRouter, Depends, Request

from app.api.deps import get_current_user
from app.core.rate_limiter import limiter
from app.schemas.search import CheckoutStateSchema, SearchRequest, SearchResponse
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

    # Coerce raw checkout dict into the typed schema so missing fields get defaults.
    # checkout is the only commerce field returned — see schemas/search.py for why
    # cart, selected_marketplaces, and clarification_question were removed.
    raw_checkout = result.get("checkout") or {}
    checkout_schema: CheckoutStateSchema | None = None
    if raw_checkout:
        checkout_schema = CheckoutStateSchema(
            active=raw_checkout.get("active", False),
            step=raw_checkout.get("step"),
            selected_cart_items=raw_checkout.get("selected_cart_items") or [],
            selected_address_id=raw_checkout.get("selected_address_id"),
            current_order_id=raw_checkout.get("current_order_id"),
            razorpay_order_id=raw_checkout.get("razorpay_order_id"),
            payment_status=raw_checkout.get("payment_status"),
            has_external=raw_checkout.get("has_external", False),
        )

    return SearchResponse(
        thread_id=result["thread_id"],
        content=result["content"],
        products=result.get("products", []),
        external_items=result.get("external_items", []),
        has_external=result.get("has_external", False),
        checkout=checkout_schema,
    )
