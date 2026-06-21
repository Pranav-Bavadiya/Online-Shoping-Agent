"""Disambiguation Node — detects ambiguity and asks for clarification if needed."""
import json
from app.core.llm_factory import get_llm, is_llm_configured
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.constants import DISAMBIGUATION_CONTEXT_MESSAGES
from app.core.logging import get_logger
from app.graph.state import AgentState

logger = get_logger(__name__)

VAGUE_TERMS = {"cheap", "best", "good", "nice", "cool", "great", "top", "affordable", "budget"}

# Normalized_query patterns that indicate a commerce action — never ask clarification.
COMMERCE_INTENT_PHRASES = {
    "add", "cart", "checkout", "buy", "purchase", "order", "pay",
    "remove", "clear", "show cart", "view cart", "my cart",
    "address", "delivery", "marketplace", "switch", "marketplace",
    "orders", "order status", "track",
}

DISAMBIGUATION_SYSTEM = """You are a shopping assistant disambiguation engine.
Your job: determine if the user's shopping query is clear enough to search for products.

A query is AMBIGUOUS if:
1. No product category can be inferred
2. Only vague terms like "cheap", "best", "good" without a product type
3. Extremely broad (e.g., just "something nice")

A query is CLEAR if:
1. A product type/category is identifiable
2. Enough keywords to search (even without price filters)
3. It is a commerce action (add to cart, checkout, buy, show cart, orders, etc.)

Return ONLY valid JSON:
{
  "is_ambiguous": true or false,
  "reason": "<why ambiguous or why clear>",
  "clarification_question": "<question to ask user if ambiguous, else null>"
}"""


async def disambiguation_node(state: AgentState) -> dict:
    logger.info("Node: disambiguation start", extra={"request_id": state.get("request_id")})

    sq = state.get("structured_query") or {}
    keywords = sq.get("keywords", [])
    category = sq.get("category", "")
    normalized_query = (sq.get("normalized_query") or "").lower()

    messages = state.get("messages", [])
    last_user_msg = ""
    for m in reversed(messages):
        role = m.get("role") if isinstance(m, dict) else getattr(m, "type", "")
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        if role in ("user", "human"):
            last_user_msg = content
            break

    lower_msg = last_user_msg.lower()

    # ── Commerce bypass ───────────────────────────────────────────────────────
    # Never ask for clarification on commerce actions — they have no keywords by design.
    if any(phrase in lower_msg for phrase in COMMERCE_INTENT_PHRASES):
        logger.info("Node: disambiguation — commerce action, skipping", extra={"request_id": state.get("request_id")})
        return {"clarification": {"pending": False, "question": None}}

    # Also bypass if normalized_query looks like a commerce action
    if any(phrase in normalized_query for phrase in COMMERCE_INTENT_PHRASES):
        logger.info("Node: disambiguation — commerce normalized_query, skipping")
        return {"clarification": {"pending": False, "question": None}}

    # ── Quick heuristic: if we have keywords or category → clear ─────────────
    non_vague_kws = [k for k in keywords if k.lower() not in VAGUE_TERMS]
    if category or non_vague_kws:
        logger.info("Node: disambiguation — clear (has keywords/category)")
        return {"clarification": {"pending": False, "question": None}}

    # ── Zero keywords + empty category → probably ambiguous ─────────────────
    # But first let the LLM decide in case context makes it clear.
    if is_llm_configured():
        context_msgs = messages[-(DISAMBIGUATION_CONTEXT_MESSAGES):]
        context_str = "\n".join(
            f"{(m.get('role') if isinstance(m, dict) else 'msg')}: "
            f"{(m.get('content') if isinstance(m, dict) else getattr(m, 'content', ''))}"
            for m in context_msgs
        )
        prompt = f"Context:\n{context_str}\n\nStructured query: {json.dumps(sq)}\nUser message: {last_user_msg}"
        try:
            llm = get_llm(temperature=0)
            resp = await llm.ainvoke([SystemMessage(content=DISAMBIGUATION_SYSTEM), HumanMessage(content=prompt)])
            raw = resp.content.strip().strip("```json").strip("```").strip()
            result = json.loads(raw)
            if result.get("is_ambiguous"):
                q = result.get("clarification_question", "Could you be more specific?")
                logger.info("Node: disambiguation — LLM ambiguous")
                return {"clarification": {"pending": True, "question": q}}
            return {"clarification": {"pending": False, "question": None}}
        except Exception as exc:
            logger.warning("Disambiguation LLM failed, proceeding as clear", extra={"error": str(exc)})

    # ── Heuristic fallback: no keywords, no LLM → ask ────────────────────────
    question = "Could you please tell me what type of product you're looking for? (e.g., headphones, laptop, shoes)"
    logger.info("Node: disambiguation — heuristic ambiguous")
    return {"clarification": {"pending": True, "question": question}}


def should_clarify(state: AgentState) -> str:
    """Conditional edge: 'clarify' or 'continue'."""
    clr = state.get("clarification") or {}
    if clr.get("pending"):
        return "clarify"
    return "continue"
