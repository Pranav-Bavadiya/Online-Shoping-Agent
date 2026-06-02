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
    step: Optional[str]
    selected_cart_items: list[str]   # cart_item_ids
    selected_address_id: Optional[str]
    payment_status: Optional[str]
    current_order_id: Optional[str]
    razorpay_order_id: Optional[str]
    payment_link: Optional[str]


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
