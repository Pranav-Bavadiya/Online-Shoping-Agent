"""Response Formatter Node — converts ranked products to MessageProductSchema dicts.

Issue #9: When no products found, return a proper apology message.
Issue #11: Response message is user-friendly and contextual, not just a bare count line.
Issue #8: Uses llm_factory instead of direct ChatOpenAI.
"""
import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm_factory import get_llm, is_llm_configured
from app.core.logging import get_logger
from app.graph.state import AgentState

logger = get_logger(__name__)

REASON_SYSTEM = """You are a helpful shopping assistant.
For each product provided, write a SHORT reason (max 15 words) why it's a good pick given the user's query.
Return ONLY a JSON array of strings, one per product.
Example: ["Great battery life for the price", "Top-rated with premium build quality"]"""

INTRO_SYSTEM = """You are a friendly shopping assistant.
Write a short, warm intro sentence (max 20 words) to present search results to the user.
The sentence should feel natural and reference what the user searched for.
Do NOT use bullet points or lists. Return just the sentence — no quotes, no preamble.
Examples:
- "Here are the best wireless headphones I found for you!"
- "I found some great laptops under ₹50,000 — take a look!"
- "Check out these top-rated running shoes matching your search!"
"""


async def formatter_node(state: AgentState) -> dict:
    logger.info("Node: formatter start", extra={"request_id": state.get("request_id")})

    products = state.get("filtered_results") or []
    sq = state.get("structured_query") or {}
    query_text = sq.get("normalized_query") or " ".join(sq.get("keywords") or [])

    # Issue #9: no products → friendly sorry message
    if not products:
        logger.info("Node: formatter — no products to format", extra={"request_id": state.get("request_id")})
        msg_content = (
            "Sorry, we weren't able to find any products matching your request. "
            "Please try different keywords or broaden your search criteria."
        )
        return {
            "final_products": [],
            "messages": [{"role": "assistant", "content": msg_content, "products": []}],
        }

    reasons = await _generate_reasons(products, query_text)

    formatted: list[dict[str, Any]] = []
    for i, p in enumerate(products):
        price_info = p.get("price") or {}
        formatted.append({
            "product_id": p.get("product_id", ""),
            "title": p.get("title", ""),
            "price": {
                "value": float(price_info.get("value") or 0),
                "currency": price_info.get("currency", "USD"),
            },
            "image": p.get("image", ""),
            "url": p.get("url", ""),
            "rating": float(p.get("rating") or 0),
            "source": p.get("source", ""),
            "short_reason": reasons[i] if i < len(reasons) else "Quality product at this price range.",
        })

    # Issue #11: generate a warm, contextual intro message
    msg_content = await _generate_intro(query_text, len(formatted))

    logger.info("Node: formatter end", extra={
        "products_formatted": len(formatted), "request_id": state.get("request_id")
    })
    return {
        "final_products": formatted,
        "messages": [{"role": "assistant", "content": msg_content, "products": formatted}],
    }


async def _generate_reasons(products: list[dict], query: str) -> list[str]:
    if not products or not is_llm_configured():
        return [_heuristic_reason(p) for p in products]
    try:
        titles = [p.get("title", "") for p in products[:10]]
        prompt = f"User query: {query}\n\nProducts:\n" + "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
        llm = get_llm(temperature=0.3)
        resp = await llm.ainvoke([SystemMessage(content=REASON_SYSTEM), HumanMessage(content=prompt)])
        raw = resp.content.strip().strip("```json").strip("```").strip()
        reasons = json.loads(raw)
        while len(reasons) < len(products):
            reasons.append(_heuristic_reason(products[len(reasons)]))
        return reasons
    except Exception as exc:
        logger.warning("Reason generation failed", extra={"error": str(exc)})
        return [_heuristic_reason(p) for p in products]


async def _generate_intro(query: str, count: int) -> str:
    """Generate a warm contextual intro sentence for the product list."""
    fallback = f"Here are {count} products matching your search."
    if not is_llm_configured():
        return fallback
    try:
        prompt = f"User searched for: {query}\nNumber of results: {count}"
        llm = get_llm(temperature=0.4)
        resp = await llm.ainvoke([SystemMessage(content=INTRO_SYSTEM), HumanMessage(content=prompt)])
        intro = resp.content.strip().strip('"').strip("'")
        return intro if intro else fallback
    except Exception as exc:
        logger.warning("Intro generation failed", extra={"error": str(exc)})
        return fallback


def _heuristic_reason(p: dict) -> str:
    rating = p.get("rating", 0)
    price_info = p.get("price") or {}
    price = price_info.get("value", 0)
    if rating >= 4.5:
        return f"Highly rated at {rating}/5 with great value."
    if price and price < 1000:
        return "Affordable option with solid specifications."
    return "Reliable choice in this category."
