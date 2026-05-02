"""Response Formatter Node — converts ranked products to MessageProductSchema dicts."""
import json
from typing import Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.core.logging import get_logger
from app.graph.state import AgentState

logger = get_logger(__name__)

REASON_SYSTEM = """You are a helpful shopping assistant.
For each product provided, write a SHORT reason (max 15 words) why it's a good pick given the user's query.
Return ONLY a JSON array of strings, one per product.
Example: ["Great battery life for the price", "Top-rated with premium build quality"]"""


async def formatter_node(state: AgentState) -> dict:
    logger.info("Node: formatter start", extra={"request_id": state.get("request_id")})

    products = state.get("filtered_results") or []
    sq = state.get("structured_query") or {}
    query_text = sq.get("normalized_query") or " ".join(sq.get("keywords") or [])

    reasons = await _generate_reasons(products, query_text)

    formatted: list[dict[str, Any]] = []
    for i, p in enumerate(products):
        price_info = p.get("price") or {}
        formatted.append({
            "product_id": p.get("product_id", ""),
            "title": p.get("title", ""),
            "price": {"value": float(price_info.get("value") or 0), "currency": price_info.get("currency", "USD")},
            "image": p.get("image", ""),
            "url": p.get("url", ""),
            "rating": float(p.get("rating") or 0),
            "source": p.get("source", ""),
            "short_reason": reasons[i] if i < len(reasons) else "Quality product at this price range.",
        })

    msg_content = f"Here are the best {len(formatted)} products matching your search."
    if not formatted:
        msg_content = "I couldn't find products matching your criteria. Try broadening your search."

    logger.info("Node: formatter end", extra={"products_formatted": len(formatted), "request_id": state.get("request_id")})
    return {
        "final_products": formatted,
        "messages": [{"role": "assistant", "content": msg_content, "products": formatted}],
    }


async def _generate_reasons(products: list[dict], query: str) -> list[str]:
    if not products or not settings.openai_api_key:
        return [_heuristic_reason(p) for p in products]
    try:
        titles = [p.get("title", "") for p in products[:10]]
        prompt = f"User query: {query}\n\nProducts:\n" + "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
        llm = ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key, temperature=0.3)
        resp = await llm.ainvoke([SystemMessage(content=REASON_SYSTEM), HumanMessage(content=prompt)])
        raw = resp.content.strip().strip("```json").strip("```").strip()
        reasons = json.loads(raw)
        # Pad with heuristic for remaining
        while len(reasons) < len(products):
            reasons.append(_heuristic_reason(products[len(reasons)]))
        return reasons
    except Exception as exc:
        logger.warning("Reason generation failed", extra={"error": str(exc)})
        return [_heuristic_reason(p) for p in products]


def _heuristic_reason(p: dict) -> str:
    rating = p.get("rating", 0)
    price_info = p.get("price") or {}
    price = price_info.get("value", 0)
    if rating >= 4.5:
        return f"Highly rated at {rating}/5 with great value."
    if price and price < 1000:
        return "Affordable option with solid specifications."
    return "Reliable choice in this category."
