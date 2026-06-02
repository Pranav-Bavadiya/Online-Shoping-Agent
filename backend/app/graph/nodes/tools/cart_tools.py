"""Cart management tools — used inside the tool loop."""
from app.core.logging import get_logger
from app.services.cart_service import (
    add_item, build_cart_summary, clear_cart, get_cart,
    remove_item, update_quantity,
)

logger = get_logger(__name__)


async def add_to_cart_tool(
    product: dict, thread_id: str, user_id: str, quantity: int = 1
) -> dict:
    """Add a product to the thread cart."""
    if not thread_id or not user_id:
        return {"status": "error", "message": "Missing thread_id or user_id"}
    if not product.get("product_id"):
        return {"status": "error", "message": "Invalid product — no product_id"}
    if not product.get("can_buy_here", True) and product.get("source") != "local":
        # External product — inform but still allow cart addition for reference
        pass
    try:
        cart = await add_item(thread_id, user_id, product, quantity)
        summary = build_cart_summary(cart)
        return {
            "status": "success",
            "message": f"Added '{product.get('title', 'product')}' to cart.",
            "cart_summary": summary,
        }
    except Exception as exc:
        logger.error("add_to_cart error", extra={"error": str(exc)})
        return {"status": "error", "message": str(exc)}


async def remove_from_cart_tool(cart_item_id: str, thread_id: str, user_id: str) -> dict:
    try:
        cart = await remove_item(thread_id, cart_item_id)
        summary = build_cart_summary(cart)
        return {"status": "success", "message": "Item removed from cart.", "cart_summary": summary}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


async def show_cart_tool(thread_id: str, user_id: str) -> dict:
    try:
        cart = await get_cart(thread_id, user_id)
        summary = build_cart_summary(cart)
        if not summary["items"]:
            return {"status": "empty", "message": "Your cart is empty.", "cart_summary": summary}
        return {"status": "success", "cart_summary": summary}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


async def update_cart_quantity_tool(
    cart_item_id: str, quantity: int, thread_id: str, user_id: str
) -> dict: 
    try:
        cart = await update_quantity(thread_id, cart_item_id, quantity)
        summary = build_cart_summary(cart)
        return {"status": "success", "message": "Cart updated.", "cart_summary": summary}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


async def clear_cart_tool(thread_id: str, user_id: str) -> dict:
    try:
        await clear_cart(thread_id)
        return {"status": "success", "message": "Cart cleared."}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
