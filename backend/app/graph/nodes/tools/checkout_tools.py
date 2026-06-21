"""Checkout tools — conversational checkout flow inside the tool loop.

Responsibilities (agent scope):
  - start_checkout   — validate cart, select purchasable items
  - list_addresses   — show saved addresses
  - select_address   — confirm delivery address → step becomes "payment_required"
  - add_address      — save a new address

Payment (Razorpay) is NOT handled by the agent.
After address selection the agent emits step="payment_required" and stops.
The frontend detects this and calls POST /checkout/payment directly.
"""
from typing import Optional
from app.core.constants import (
    CHECKOUT_STEP_ADDRESS, CHECKOUT_STEP_DONE, CHECKOUT_STEP_INIT,
    CHECKOUT_STEP_ITEMS, CHECKOUT_STEP_PAYMENT_REQUIRED,
)
from app.core.logging import get_logger
from app.db import collections as col
from app.services.cart_service import build_cart_summary, get_cart

logger = get_logger(__name__)


async def start_checkout_tool(
    thread_id: str,
    user_id: str,
    cart_item_ids: Optional[list[str]] = None,
) -> dict:
    """Initiate checkout. cart_item_ids=None means all purchasable items."""
    cart = await get_cart(thread_id, user_id)
    summary = build_cart_summary(cart)
    all_items = summary["items"]
    purchasable = summary["purchasable_items"]
    external = summary["external_items"]

    if not all_items:
        return {"status": "error", "message": "Your cart is empty. Add products before checking out."}

    # Prepare external items info with full details for frontend rendering
    external_info = [
        {
            "title": i["title"],
            "redirect_url": i.get("redirect_url", ""),
            "cart_item_id": i["cart_item_id"],
            "image": i.get("image", ""),
            "price": i.get("price", {}),
            "source": i.get("source", "external"),
            "can_buy_here": False,
        }
        for i in external
    ] if external else []

    if not purchasable:
        ext_lines = "\n".join(
            f"• {i['title']} — {i.get('redirect_url', 'No URL available')}"
            for i in external
        )
        return {
            "status": "external_only",
            "message": (
                "Your cart only contains external marketplace products that cannot be "
                "purchased here. Please visit the original marketplace sites:\n" + ext_lines
            ),
            "external_items": external_info,
        }

    # Determine which local items to checkout
    if cart_item_ids:
        selected = [i for i in purchasable if i["cart_item_id"] in cart_item_ids]
        if not selected:
            return {"status": "error", "message": "None of the selected items are purchasable here."}
    else:
        selected = purchasable

    subtotal = sum(float(i["price"]["value"]) * i.get("quantity", 1) for i in selected)
    currency = selected[0]["price"].get("currency", "INR") if selected else "INR"

    result = {
        "status": "success",
        "step": CHECKOUT_STEP_ITEMS,
        "selected_items": selected,
        "selected_item_ids": [i["cart_item_id"] for i in selected],
        "subtotal": round(subtotal, 2),
        "currency": currency,
        "message": (
            f"Starting checkout for {len(selected)} local item(s) totalling "
            f"{currency} {subtotal:.2f}. Let me pull up your saved addresses... 📦"
        ),
        "has_external": bool(external_info),
        "external_items": external_info,
    }

    if external_info:
        ext_lines = "\n".join(f"• {i['title']} — {i['redirect_url']}" for i in external_info)
        result["external_notice"] = (
            "⚠️ You also have external products in your cart that cannot be purchased here.\n"
            + ext_lines
            + "\n\nHave you visited these external sites? Would you like me to remove them from your cart?"
        )

    return result


async def select_address_tool(
    user_id: str, address_id: str
) -> dict:
    """Select delivery address. After this the agent hands off to frontend for payment."""
    user = await col.users().find_one({"_id": user_id})
    if not user:
        return {"status": "error", "message": "User not found."}
    addresses = user.get("addresses", [])
    chosen = next((a for a in addresses if a["id"] == address_id), None)
    if not chosen:
        return {
            "status": "not_found",
            "message": "Address not found. Please add a new address or choose from existing ones.",
            "addresses": addresses,
        }
    return {
        "status": "success",
        # Use payment_required so the frontend knows to launch the payment widget
        "step": CHECKOUT_STEP_PAYMENT_REQUIRED,
        "address": chosen,
        "message": (
            f"✅ Delivery address confirmed: {chosen['line1']}, {chosen['city']}, {chosen['pincode']}.\n\n"
            "A payment widget will appear for you to complete the purchase securely. 💳"
        ),
    }


async def add_address_tool(
    user_id: str,
    line1: str, city: str, state: str, pincode: str,
    line2: str = "", country: str = "India",
) -> dict:
    """Add a new delivery address."""
    from app.utils.uuid import new_request_id
    address = {
        "id": f"addr_{new_request_id()[:8]}",
        "line1": line1, "line2": line2,
        "city": city, "state": state,
        "pincode": pincode, "country": country,
    }
    await col.users().update_one(
        {"_id": user_id},
        {"$push": {"addresses": address}},
    )
    return {
        "status": "success",
        # Address added — still need selection confirmation before payment_required
        "step": CHECKOUT_STEP_ADDRESS,
        "address": address,
        "message": f"Address saved: {line1}, {city}. Shall I use this for delivery?",
    }


async def list_addresses_tool(user_id: str) -> dict:
    user = await col.users().find_one({"_id": user_id})
    if not user:
        return {"status": "error", "message": "User not found."}
    addresses = user.get("addresses", [])
    if not addresses:
        return {
            "status": "no_addresses",
            "message": "You don't have any saved addresses yet. Please provide your delivery address and I'll save it for future orders.",
            "addresses": [],
        }
    addr_list = "\n".join(
        f"{i+1}. {a['line1']}, {a['city']}, {a['pincode']} (ID: {a['id']})"
        for i, a in enumerate(addresses)
    )
    return {
        "status": "success",
        "addresses": addresses,
        "message": (
            f"Here are your saved addresses:\n{addr_list}\n\n"
            "Which one would you like to use for delivery? Or would you like to add a new address?"
        ),
    }
