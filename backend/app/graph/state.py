"""LangGraph state schema — STRICT as per spec."""
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
    decision: str           # reuse | partial | new
    cache_doc_id: Optional[str]


class ToolContext(TypedDict, total=False):
    last_tool_used: str
    last_tool_status: str   # found | not_found
    last_product_id: str
    iteration: int


class ConversationContext(TypedDict, total=False):
    last_product_id: str
    last_category: str


class ClarificationInfo(TypedDict, total=False):
    pending: bool
    question: Optional[str]


class AgentState(TypedDict):
    # Core message history — managed by add_messages reducer
    messages: Annotated[list[Any], add_messages]

    # Current query intent
    intent: Optional[str]                  # search | chat

    # Structured query extracted by LLM
    structured_query: Optional[StructuredQuery]

    # Cache / retrieval metadata
    retrieval: Optional[RetrievalInfo]

    # Raw results from API (before filtering)
    raw_results: Optional[list[dict]]

    # Filtered + ranked results ready for formatting
    filtered_results: Optional[list[dict]]

    # Tool agent context
    tool_context: Optional[ToolContext]

    # Conversation context (last seen product/category)
    conversation_context: Optional[ConversationContext]

    # Disambiguation / clarification state
    clarification: Optional[ClarificationInfo]

    # Final formatted products
    final_products: Optional[list[dict]]

    # User feedback summary injected before ranking
    user_feedback_summary: Optional[dict]

    # Request metadata
    user_id: Optional[str]
    thread_id: Optional[str]
    request_id: Optional[str]
