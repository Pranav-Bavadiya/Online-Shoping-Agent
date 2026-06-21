"""LangGraph state schema — upgraded with commerce capabilities."""
from typing import Annotated, Any, Optional
from typing_extensions import TypedDict
from langgraph.graph import add_messages


class PriceFilter(TypedDict, total=False):
    min: float
    max: float


class StructuredQuery(TypedDict, total=False):
    category: str
    keywords: list[str]
    price_filter: PriceFilter
    normalized_query: str
    source: str
    required_types: list[str]   # e.g. ["red shirts", "blue jeans"] for multi-type queries
    brand_strict: str           # e.g. "samsung" when user explicitly requests one brand only
    selected_marketplaces: list[str]


class RetrievalInfo(TypedDict, total=False):
    cache_hit: bool
    decision: str
    cache_doc_id: Optional[str]
    cache_filters: Optional[dict]


class ToolContext(TypedDict, total=False):
    last_tool_used: str
    last_tool_status: str
    last_product_id: str
    iteration: int
    action: str
    last_raw_result: Optional[dict]


class ConversationContext(TypedDict, total=False):
    last_product_id: str
    last_category: str
    last_shown_products: list[dict]
    marketplace_preferences: list[str]
    recently_referenced_products: list[str]


class ClarificationInfo(TypedDict, total=False):
    pending: bool
    question: Optional[str]


class CartItem(TypedDict, total=False):
    cart_item_id: str
    product_id: str
    title: str
    price: dict
    image: str
    source: str
    can_buy_here: bool
    redirect_url: str
    quantity: int
    added_at: str


class ThreadCart(TypedDict, total=False):
    items: list[CartItem]


class CheckoutState(TypedDict, total=False):
    active: bool
    # Possible step values (see constants.py):
    #   "items_selected"   — agent selected items
    #   "address_selected" — intermediate, address being added
    #   "payment_required" — agent done, frontend must call POST /checkout/payment
    #   "payment_created"  — REST endpoint created Razorpay order
    #   "done"             — REST endpoint confirmed payment
    step: Optional[str]
    selected_cart_items: list[str]   # cart_item_ids of purchasable items
    selected_address_id: Optional[str]
    _selected_address: Optional[dict]  # full address object used by REST /checkout/payment
    payment_status: Optional[str]
    current_order_id: Optional[str]
    razorpay_order_id: Optional[str]
    has_external: bool               # True when cart has external (non-purchasable) items
    external_items: list[dict]       # full details of external items for frontend display


class AgentState(TypedDict):
    messages: Annotated[list[Any], add_messages]
    intent: Optional[str]
    structured_query: Optional[StructuredQuery]
    retrieval: Optional[RetrievalInfo]
    raw_results: Optional[list[dict]]
    filtered_results: Optional[list[dict]]
    tool_context: Optional[ToolContext]
    conversation_context: Optional[ConversationContext]
    clarification: Optional[ClarificationInfo]
    final_products: Optional[list[dict]]
    user_feedback_summary: Optional[dict]

    # Commerce state
    selected_marketplaces: Optional[list[str]]
    thread_cart: Optional[ThreadCart]
    checkout: Optional[CheckoutState]

    # Request metadata
    user_id: Optional[str]
    thread_id: Optional[str]
    request_id: Optional[str]
