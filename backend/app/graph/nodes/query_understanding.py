"""Query Understanding Node — extracts structured_query from user message using LLM."""
import json
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.core.constants import QUERY_CONTEXT_MESSAGES
from app.core.logging import get_logger
from app.graph.state import AgentState

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are a shopping query understanding engine.
Extract structured information from the user's shopping query.

Return ONLY valid JSON with this exact schema:
{
  "category": "<product category or empty string>",
  "keywords": ["<keyword1>", "<keyword2>"],
  "price_filter": {"min": <number or 0>, "max": <number or 0>},
  "normalized_query": "<clean version of query>"
}

Rules:
- Use conversation context to resolve follow-ups (e.g., "under 2000" → use last category)
- Extract price numbers from text (e.g., "under 2000" → max: 2000)
- If no price mentioned, use 0
- keywords should be meaningful search terms, not stop words
- category examples: electronics, headphones, smartphones, laptops, clothing, shoes"""


def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )


async def query_understanding_node(state: AgentState) -> dict:
    logger.info("Node: query_understanding start", extra={
        "request_id": state.get("request_id"),
        "thread_id": state.get("thread_id"),
    })

    messages = state.get("messages", [])
    if not messages:
        return {"structured_query": {"category": "", "keywords": [], "price_filter": {"min": 0, "max": 0}, "normalized_query": ""}}

    # Get the latest user message
    last_user_msg = ""
    for msg in reversed(messages):
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "type", "")
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
        if role in ("user", "human"):
            last_user_msg = content
            break

    # Build context from last N messages
    context_msgs = messages[-(QUERY_CONTEXT_MESSAGES):]
    context_str = "\n".join(
        f"{(m.get('role') if isinstance(m, dict) else getattr(m, 'type', 'unknown'))}: "
        f"{(m.get('content') if isinstance(m, dict) else getattr(m, 'content', ''))}"
        for m in context_msgs
    )

    conv_ctx = state.get("conversation_context") or {}
    last_category = conv_ctx.get("last_category", "")

    prompt = f"""Conversation so far:
{context_str}

Last category seen: {last_category or 'none'}

Current user query: {last_user_msg}

Extract structured query:"""

    # Fallback if no API key
    if not settings.openai_api_key:
        logger.warning("No OpenAI API key — using heuristic query parser")
        structured = _heuristic_parse(last_user_msg)
    else:
        try:
            llm = _get_llm()
            resp = await llm.ainvoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)])
            raw = resp.content.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").replace("json", "").strip()
            structured = json.loads(raw)
        except Exception as exc:
            logger.error("LLM query understanding failed", extra={"error": str(exc)})
            structured = _heuristic_parse(last_user_msg)

    structured["source"] = "ebay"
    logger.info("Node: query_understanding end", extra={
        "structured_query": structured,
        "request_id": state.get("request_id"),
    })
    return {"structured_query": structured}


def _heuristic_parse(query: str) -> dict:
    """Simple keyword+price extractor when LLM unavailable."""
    import re
    price_max = 0.0
    price_min = 0.0
    price_match = re.search(r"under\s*[\₹$]?\s*([\d,]+)", query, re.IGNORECASE)
    if price_match:
        price_max = float(price_match.group(1).replace(",", ""))
    between = re.search(r"([\d,]+)\s*(?:to|-)\s*([\d,]+)", query, re.IGNORECASE)
    if between:
        price_min = float(between.group(1).replace(",", ""))
        price_max = float(between.group(2).replace(",", ""))
    stopwords = {"i", "want", "need", "find", "show", "me", "best", "good", "cheap", "a", "an", "the"}
    words = [w for w in re.findall(r"\w+", query.lower()) if w not in stopwords]
    return {
        "category": "",
        "keywords": words[:5],
        "price_filter": {"min": price_min, "max": price_max},
        "normalized_query": query.strip().lower(),
    }
