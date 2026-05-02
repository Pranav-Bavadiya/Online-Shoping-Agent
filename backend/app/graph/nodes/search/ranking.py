"""Ranking Node — ranks products using quality, rating, and user feedback boosts."""
from app.core.constants import (
    FEEDBACK_CLICK_BOOST, FEEDBACK_IGNORE_PENALTY,
    FEEDBACK_LIKE_BOOST, MAX_SEARCH_RESULTS_RETURNED,
)
from app.core.logging import get_logger
from app.graph.state import AgentState

logger = get_logger(__name__)


def _compute_score(product: dict, feedback_summary: dict) -> float:
    """Compute composite ranking score."""
    rating = float(product.get("rating") or 0)
    price_info = product.get("price") or {}
    price = float(price_info.get("value") or 0)
    pid = product.get("product_id", "")

    # Normalise rating (0–5 → 0–1)
    rating_score = rating / 5.0

    # Price attractiveness: lower is better (relative score if price known)
    price_score = 0.5  # neutral when price unknown
    if price > 0:
        # Simple heuristic: cheaper → slightly better score (capped)
        price_score = max(0.0, min(1.0, 1 - (price / 100000)))

    base = 0.6 * rating_score + 0.4 * price_score

    # Feedback boosts
    fb = feedback_summary.get(pid) or {}
    if fb.get("like"):
        base += FEEDBACK_LIKE_BOOST
    if fb.get("click"):
        base += FEEDBACK_CLICK_BOOST
    if fb.get("ignore"):
        base += FEEDBACK_IGNORE_PENALTY

    return round(base, 6)


async def ranking_node(state: AgentState) -> dict:
    logger.info("Node: ranking start", extra={"request_id": state.get("request_id")})

    products = list(state.get("filtered_results") or [])
    feedback_summary = state.get("user_feedback_summary") or {}

    scored = [(p, _compute_score(p, feedback_summary)) for p in products]
    scored.sort(key=lambda x: x[1], reverse=True)

    ranked = [p for p, _ in scored[:MAX_SEARCH_RESULTS_RETURNED]]

    logger.info("Node: ranking end", extra={"ranked": len(ranked), "request_id": state.get("request_id")})
    return {"filtered_results": ranked}
