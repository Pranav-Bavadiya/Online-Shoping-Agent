"""Marketplace switching tool."""
from app.core.constants import ALL_MARKETPLACES
from app.core.logging import get_logger

logger = get_logger(__name__)


async def change_marketplaces_tool(marketplaces: list[str]) -> dict:
    """Update selected marketplaces for the current session."""
    valid = [m.lower() for m in marketplaces if m.lower() in ALL_MARKETPLACES]
    if not valid:
        return {
            "status": "error",
            "message": f"No valid marketplaces provided. Available: {', '.join(ALL_MARKETPLACES)}",
        }
    return {
        "status": "success",
        "selected_marketplaces": valid,
        "message": f"Now searching in: {', '.join(valid).title()}. Your next search will use these marketplaces.",
    }
