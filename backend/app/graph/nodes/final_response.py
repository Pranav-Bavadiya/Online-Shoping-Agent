"""Final Response Node — builds the last assistant message for clarification requests."""
from app.core.logging import get_logger
from app.graph.state import AgentState

logger = get_logger(__name__)


async def clarification_response_node(state: AgentState) -> dict:
    """Emit a clarification question as the assistant message and pause."""
    logger.info("Node: clarification_response start", extra={"request_id": state.get("request_id")})

    clr = state.get("clarification") or {}
    question = clr.get("question") or "Could you please clarify your request?"

    logger.info("Node: clarification_response — asking question", extra={
        "question": question,
        "request_id": state.get("request_id"),
    })

    # Include external_items and has_external so search_service can read all
    # fields it needs from the single last assistant message consistently.
    return {
        "messages": [{
            "role": "assistant",
            "content": question,
            "products": [],
            "external_items": [],
            "has_external": False,
        }],
        "final_products": [],
    }
