"""Disambiguation Node — detects ambiguity and asks for clarification if needed."""
import json
from app.core.llm_factory import get_llm, is_llm_configured
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.constants import DISAMBIGUATION_CONTEXT_MESSAGES
from app.core.logging import get_logger
from app.graph.state import AgentState

logger = get_logger(__name__)

VAGUE_TERMS = {"cheap", "best", "good", "nice", "cool", "great", "top", "affordable", "budget"}

DISAMBIGUATION_SYSTEM = """You are a shopping assistant disambiguation engine.
Your job: determine if the user's shopping query is clear enough to search for products.

A query is AMBIGUOUS if:
1. No product category can be inferred
2. Only vague terms like "cheap", "best", "good" without a product type
3. Extremely broad (e.g., just "something nice")

A query is CLEAR if:
1. A product type/category is identifiable
2. Enough keywords to search (even without price filters)

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

    messages = state.get("messages", [])
    last_user_msg = ""
    for m in reversed(messages):
        role = m.get("role") if isinstance(m, dict) else getattr(m, "type", "")
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        if role in ("user", "human"):
            last_user_msg = content
            break

    # Quick heuristic: if we have 0 keywords and empty category → ambiguous
    non_vague_kws = [k for k in keywords if k.lower() not in VAGUE_TERMS]
    if not category and not non_vague_kws:
        question = "Could you please tell me what type of product you're looking for? (e.g., headphones, laptop, shoes)"
        logger.info("Node: disambiguation — heuristic ambiguous", extra={"request_id": state.get("request_id")})
        return {
            "clarification": {"pending": True, "question": question},
        }

    # LLM-based disambiguation for edge cases
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
                logger.info("Node: disambiguation — LLM ambiguous", extra={"request_id": state.get("request_id")})
                return {"clarification": {"pending": True, "question": q}}
        except Exception as exc:
            logger.warning("Disambiguation LLM failed, proceeding as clear", extra={"error": str(exc)})

    logger.info("Node: disambiguation — clear", extra={"request_id": state.get("request_id")})
    return {"clarification": {"pending": False, "question": None}}


def should_clarify(state: AgentState) -> str:
    """Conditional edge: 'clarify' or 'continue'."""
    clr = state.get("clarification") or {}
    if clr.get("pending"):
        return "clarify"
    return "continue"
