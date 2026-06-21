"""Search request/response schemas."""
from typing import Optional
from pydantic import BaseModel
from app.schemas.product import MessageProductSchema, ExternalItemSchema


class SearchRequest(BaseModel):
    query: str
    thread_id: Optional[str] = None


class CheckoutStateSchema(BaseModel):
    """
    Typed checkout state embedded in every SearchResponse.
    Frontend should watch for step == "payment_required" to trigger the
    Razorpay payment widget via POST /checkout/payment.
    """
    active: bool = False
    step: Optional[str] = None
    # "payment_required" → frontend calls POST /checkout/payment
    # "payment_created"  → Razorpay order exists, widget should be open
    # "done"             → order placed, show confirmation
    selected_cart_items: list[str] = []
    selected_address_id: Optional[str] = None
    current_order_id: Optional[str] = None
    razorpay_order_id: Optional[str] = None
    payment_status: Optional[str] = None
    has_external: bool = False


class SearchResponse(BaseModel):
    thread_id: str
    content: str
    products: list[MessageProductSchema] = []
    external_items: list[ExternalItemSchema] = []
    has_external: bool = False
    # checkout is kept: checkout.step == "payment_required" is a structural
    # signal the frontend needs (not narrated as text) to trigger the
    # Razorpay payment widget. See CheckoutStateSchema for all step values.
    #
    # Removed fields (now redundant, see search_service.py for rationale):
    #   - clarification_question: the question text is already in `content`
    #   - cart: narrated in `content` on show_cart; also has its own
    #     dedicated endpoint GET /threads/{thread_id}/cart
    #   - selected_marketplaces: narrated in `content` on change_marketplaces
    checkout: Optional[CheckoutStateSchema] = None
