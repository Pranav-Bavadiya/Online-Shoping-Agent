"""Intent Router Node — routes to 'search' or 'chat' flow."""
import json
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.core.constants import INTENT_CHAT, INTENT_SEARCH
from app.core.logging import get_logger
from app.graph.state import AgentState

logger = get_logger(__name__)

ROUTER_SYSTEM = """You are a shopping assistant intent classifier.

Classify the user's latest message as either:
- "search": user wants to find/browse products (e.g., "show me headphones", "find laptops under 50000")
- "chat": user has a question, wants details about a product, comparison, advice, or general conversation

Return ONLY valid JSON:
{"intent": "search" or "chat"}"""

SEARCH_KEYWORDS = {
    "find", "show", "search", "buy", "get", "looking for", "want to buy",
    "recommendations", "suggest", "options", "list", "best", "top",
}

CHAT_KEYWORDS = {
    "compare", "tell me", "what about", "how is", "is it", "quality",
    "difference", "better", "pros and cons", "review", "feedback",
    "details", "more info", "specifications", "explain", "describe",
    "what's the", "which is", "do you think", "opinion", "recommend",
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

    sq = state.get("structured_query") or {}
    lower = last_user_msg.lower()

    # Heuristic: Check for chat intent first (questions, comparisons, etc.)
    if any(kw in lower for kw in CHAT_KEYWORDS):
        intent = INTENT_CHAT
        logger.info("Node: intent_router — CHAT detected (keyword)", extra={"request_id": state.get("request_id")})
        return {"intent": intent}

    # Heuristic: Check for search intent (product browsing, finding, etc.)
    if any(kw in lower for kw in SEARCH_KEYWORDS):
        if sq.get("keywords") or sq.get("category"):
            intent = INTENT_SEARCH
            logger.info("Node: intent_router — SEARCH detected (keyword)", extra={"request_id": state.get("request_id")})
            return {"intent": intent}

    # If no clear heuristic signal, use LLM or default
    if settings.openai_api_key:
        try:
            context_msgs = messages[-5:]
            context_str = "\n".join(
                f"{(m.get('role') if isinstance(m, dict) else 'msg')}: "
                f"{(m.get('content') if isinstance(m, dict) else getattr(m, 'content', ''))}"
                for m in context_msgs
            )
            prompt = f"Conversation:\n{context_str}\n\nLatest message: {last_user_msg}\nStructured query: {json.dumps(sq)}"
            llm = ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key, temperature=0)
            resp = await llm.ainvoke([SystemMessage(content=ROUTER_SYSTEM), HumanMessage(content=prompt)])
            raw = resp.content.strip().strip("```json").strip("```").strip()
            result = json.loads(raw)
            intent = result.get("intent", INTENT_SEARCH)
            logger.info("Node: intent_router — intent via LLM", extra={"intent": intent, "request_id": state.get("request_id")})
        except Exception as exc:
            logger.warning("Intent router LLM failed, defaulting to search", extra={"error": str(exc)})
            intent = INTENT_SEARCH
    else:
        # No LLM and no clear signal → default to search if we have keywords
        intent = INTENT_SEARCH if sq.get("keywords") else INTENT_CHAT
        logger.info("Node: intent_router — default fallback", extra={"intent": intent})

    logger.info("Node: intent_router end", extra={"intent": intent, "request_id": state.get("request_id")})
    return {"intent": intent}


def route_by_intent(state: AgentState) -> str:
    """Conditional edge: 'search' or 'chat'."""
    return state.get("intent", INTENT_SEARCH)
