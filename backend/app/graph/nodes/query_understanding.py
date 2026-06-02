"""Query Understanding Node — extracts structured_query from user message."""
import json
from langchain_core.messages import HumanMessage, SystemMessage
from app.core.constants import QUERY_CONTEXT_MESSAGES
from app.core.llm_factory import get_llm, is_llm_configured
from app.core.logging import get_logger
from app.graph.state import AgentState

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are a shopping query understanding engine.
Extract structured information from the user's message.

Return ONLY valid JSON with this exact schema:
{
  "category": "<product category or empty string>",
  "keywords": ["<keyword1>", "<keyword2>"],
  "price_filter": {"min": <number or 0>, "max": <number or 0>},
  "normalized_query": "<complete standalone search query>"
}

Rules:
- For product search queries: extract category, keywords, price filters.
- For commerce commands (add to cart, checkout, show cart, buy): set category="" and keywords=[].
  normalized_query should describe the action, e.g. "add product to cart".
- Use conversation context for follow-up queries — include the original product intent.
- Extract prices: "under 2000" → max:2000, "above 500" → min:500.
- If no price mentioned, use 0 for both.
- Keywords: meaningful terms only, no stop words.

Refinement rule: user says "show cheaper ones", "wireless ones", "Samsung only" →
generate COMPLETE query merging original intent + new conditions.
Example: original=headphones, new=wireless under 1500 → "wireless headphones under 1500"
"""


async def query_understanding_node(state: AgentState) -> dict:
    logger.info("Node: query_understanding start", extra={"request_id": state.get("request_id")})

    messages = state.get("messages", [])
    if not messages:
        return {"structured_query": {"category": "", "keywords": [], "price_filter": {"min": 0, "max": 0}, "normalized_query": ""}}

    last_user_msg = ""
    for msg in reversed(messages):
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "type", "")
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
        if role in ("user", "human"):
            last_user_msg = content
            break

    if not last_user_msg.strip():
        return {"structured_query": {"category": "", "keywords": [], "price_filter": {"min": 0, "max": 0}, "normalized_query": ""}}

    context_msgs = messages[-(QUERY_CONTEXT_MESSAGES):]
    context_str = "\n".join(
        f"{(m.get('role') if isinstance(m, dict) else 'msg')}: "
        f"{(m.get('content') if isinstance(m, dict) else getattr(m, 'content', ''))}"
        for m in context_msgs
    )
    prompt = f"Conversation context:\n{context_str}\n\nLatest user message: {last_user_msg}"

    structured = None
    if not is_llm_configured():
        structured = _heuristic_parse(last_user_msg)
    else:
        try:
            llm = get_llm(temperature=0)
            resp = await llm.ainvoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)])
            raw = resp.content.strip().strip("```json").strip("```").strip()
            structured = json.loads(raw)
        except Exception as exc:
            logger.warning("Query understanding LLM failed", extra={"error": str(exc)})
            structured = _heuristic_parse(last_user_msg)

    # Carry forward selected_marketplaces into the structured query
    selected_markets = state.get("selected_marketplaces")
    if selected_markets:
        structured["selected_marketplaces"] = selected_markets

    logger.info("Node: query_understanding end", extra={
        "category": structured.get("category"), "keywords": structured.get("keywords"),
        "request_id": state.get("request_id"),
    })
    return {"structured_query": structured}


def _heuristic_parse(msg: str) -> dict:
    import re
    lower = msg.lower()
    price_max = 0.0
    price_min = 0.0
    m = re.search(r"under\s+(\d+)", lower)
    if m:
        price_max = float(m.group(1))
    m = re.search(r"above\s+(\d+)|min\s+(\d+)", lower)
    if m:
        price_min = float(m.group(1) or m.group(2))
    stop = {"show", "find", "get", "me", "a", "the", "some", "good", "best", "i", "want", "buy", "please"}
    keywords = [w for w in lower.split() if w not in stop and len(w) > 2][:5]
    return {
        "category": "",
        "keywords": keywords,
        "price_filter": {"min": price_min, "max": price_max},
        "normalized_query": msg.strip(),
    }
