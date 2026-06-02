"""Response Formatter Node — adds commerce metadata to products."""
import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm_factory import get_llm, is_llm_configured
from app.core.logging import get_logger
from app.graph.state import AgentState

logger = get_logger(__name__)

REASON_SYSTEM = """You are a helpful shopping assistant.
For each product provided, write a SHORT reason (max 15 words) why it's a good pick.
Return ONLY a JSON array of strings, one per product.
Example: ["Great battery life for the price", "Top-rated with premium build quality"]"""

INTRO_SYSTEM = """You are a friendly shopping assistant. Write a short warm intro (max 20 words)
to present search results. Feel natural, reference what was searched. Return just the sentence."""

ONBOARDING_MSG = """👋 Welcome! I'm your AI shopping assistant. Here's what I can do:

🛒 **Cart**: Add/remove products via chat ("Add the first one to my cart")
🏪 **Marketplaces**: Search Local, eBay, or both ("Show only local products")
💳 **Checkout**: Buy products conversationally ("Checkout my cart")
🎯 **Selective buy**: Purchase specific items ("Buy 1st and 3rd only")
🔗 **External products**: eBay/Amazon items show redirect links

Let's start shopping! What are you looking for?"""


async def formatter_node(state: AgentState) -> dict:
    logger.info("Node: formatter start", extra={"request_id": state.get("request_id")})

    products = state.get("filtered_results") or []
    sq = state.get("structured_query") or {}
    query_text = sq.get("normalized_query") or " ".join(sq.get("keywords") or [])
    is_new = _is_new_conversation(state)

    if not products:
        msg_content = (
            "Sorry, we weren't able to find any products matching your request. "
            "Please try different keywords or broaden your search criteria."
        )
        if is_new:
            msg_content = ONBOARDING_MSG + "\n\n" + msg_content
        return {
            "final_products": [],
            "messages": [{"role": "assistant", "content": msg_content, "products": []}],
        }

    reasons = await _generate_reasons(products, query_text)
    formatted: list[dict[str, Any]] = []
    for i, p in enumerate(products):
        price_info = p.get("price") or {}
        source = p.get("source", "")
        can_buy = p.get("can_buy_here", source == "local")
        formatted.append({
            "product_id": p.get("product_id", ""),
            "title": p.get("title", ""),
            "price": {"value": float(price_info.get("value") or 0), "currency": price_info.get("currency", "INR")},
            "image": p.get("image", ""),
            "url": p.get("url", ""),
            "rating": float(p.get("rating") or 0),
            "source": source,
            "short_reason": reasons[i] if i < len(reasons) else "Quality product at this price range.",
            "can_buy_here": can_buy,
            "redirect_url": p.get("redirect_url") or p.get("url", ""),
            "cart_supported": True,
        })

    msg_content = await _generate_intro(query_text, len(formatted))
    if is_new:
        msg_content = ONBOARDING_MSG + "\n\n" + msg_content

    logger.info("Node: formatter end", extra={"products_formatted": len(formatted)})
    return {
        "final_products": formatted,
        "messages": [{"role": "assistant", "content": msg_content, "products": formatted}],
    }


def _is_new_conversation(state: AgentState) -> bool:
    messages = state.get("messages", [])
    assistant_msgs = [m for m in messages if (m.get("role") if isinstance(m, dict) else "") == "assistant"]
    return len(assistant_msgs) == 0


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
    fallback = f"Here are {count} products matching your search."
    if not is_llm_configured():
        return fallback
    try:
        prompt = f"User searched for: {query}\nNumber of results: {count}"
        llm = get_llm(temperature=0.4)
        resp = await llm.ainvoke([SystemMessage(content=INTRO_SYSTEM), HumanMessage(content=prompt)])
        intro = resp.content.strip().strip('"').strip("'")
        return intro or fallback
    except Exception:
        return fallback


def _heuristic_reason(p: dict) -> str:
    rating = p.get("rating", 0)
    price = (p.get("price") or {}).get("value", 0)
    if rating >= 4.5:
        return f"Highly rated at {rating}/5 — excellent value."
    if price and price < 1000:
        return "Affordable option with solid specifications."
    return "Reliable choice in this category."
