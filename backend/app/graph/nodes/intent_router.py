"""Intent Router Node — routes to 'search' or 'chat' (tool-loop) flow.

Commerce actions (cart/checkout/marketplace) always route to chat/tool-loop.
"""
import json
from app.core.llm_factory import get_llm, is_llm_configured
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.constants import INTENT_CHAT, INTENT_SEARCH
from app.core.logging import get_logger
from app.graph.state import AgentState

logger = get_logger(__name__)

ROUTER_SYSTEM = """You are a shopping assistant intent classifier.

Classify the user's latest message as:
- "search": user wants to FIND/BROWSE NEW products (e.g., "show me headphones", "find laptops under 50000")
- "chat": anything else — questions, product details, cart/checkout actions, comparisons, advice, greetings

ALWAYS return "chat" for:
- cart actions: "add to cart", "remove", "show cart", "clear cart"
- checkout/payment: "buy", "checkout", "purchase", "pay", "order"
- marketplace switching: "use Amazon", "switch to eBay", "local only"
- product details: "tell me more", "details", "specs", "compare"
- general questions or conversation

Return ONLY valid JSON: {"intent": "search" or "chat"}"""

# Commerce keywords always → chat/tool-loop
COMMERCE_KEYWORDS = {
    "add to cart", "add it to", "remove from cart", "show cart", "view cart",
    "my cart", "clear cart", "checkout", "buy now", "purchase", "pay",
    "order now", "place order", "delivery", "address", "payment",
    "switch to", "use ebay", "use amazon", "use local", "local only",
    "ebay only", "marketplace",
}

SEARCH_KEYWORDS = {
    "find", "show me", "search for", "looking for", "browse",
    "recommendations", "suggest", "list", "options",
}

CHAT_KEYWORDS = {
    "compare", "tell me", "what about", "how is", "is it good",
    "difference", "better", "pros and cons", "review", "details",
    "more info", "specifications", "explain", "which is", "opinion",
}


async def intent_router_node(state: AgentState) -> dict:
    logger.info("Node: intent_router start", extra={"request_id": state.get("request_id")})

    messages = state.get("messages", [])
    last_user_msg = ""
    for m in reversed(messages):
        role = m.get("role") if isinstance(m, dict) else getattr(m, "type", "")
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        if role in ("user", "human"):
            last_user_msg = content
            break

    lower = last_user_msg.lower()
    sq = state.get("structured_query") or {}

    # Commerce keywords → always tool-loop
    if any(kw in lower for kw in COMMERCE_KEYWORDS):
        logger.info("Node: intent_router — COMMERCE → chat", extra={"request_id": state.get("request_id")})
        return {"intent": INTENT_CHAT}

    # Explicit chat keywords
    if any(kw in lower for kw in CHAT_KEYWORDS):
        logger.info("Node: intent_router — CHAT (keyword)")
        return {"intent": INTENT_CHAT}

    # Explicit search keywords with structured query content
    if any(kw in lower for kw in SEARCH_KEYWORDS):
        if sq.get("keywords") or sq.get("category"):
            logger.info("Node: intent_router — SEARCH (keyword)")
            return {"intent": INTENT_SEARCH}

    # LLM fallback
    if is_llm_configured():
        try:
            context_str = "\n".join(
                f"{(m.get('role') if isinstance(m, dict) else 'msg')}: "
                f"{(m.get('content') if isinstance(m, dict) else getattr(m, 'content', ''))}"
                for m in messages[-5:]
            )
            prompt = f"Conversation:\n{context_str}\n\nLatest: {last_user_msg}\nQuery: {json.dumps(sq)}"
            llm = get_llm(temperature=0)
            resp = await llm.ainvoke([SystemMessage(content=ROUTER_SYSTEM), HumanMessage(content=prompt)])
            raw = resp.content.strip().strip("```json").strip("```").strip()
            intent = json.loads(raw).get("intent", INTENT_SEARCH)
            logger.info("Node: intent_router — LLM intent", extra={"intent": intent})
            return {"intent": intent}
        except Exception as exc:
            logger.warning("Intent router LLM failed", extra={"error": str(exc)})

    # Default: use search if we have structured keywords, else chat
    intent = INTENT_SEARCH if (sq.get("keywords") or sq.get("category")) else INTENT_CHAT
    logger.info("Node: intent_router — default", extra={"intent": intent})
    return {"intent": intent}


def route_by_intent(state: AgentState) -> str:
    return state.get("intent", INTENT_SEARCH)
