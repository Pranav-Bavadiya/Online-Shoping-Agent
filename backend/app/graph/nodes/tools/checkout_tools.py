"""Checkout tools — conversational checkout flow inside the tool loop."""
from typing import Optional
from app.core.constants import (
    CHECKOUT_STEP_ADDRESS, CHECKOUT_STEP_DONE, CHECKOUT_STEP_INIT,
    CHECKOUT_STEP_ITEMS, CHECKOUT_STEP_PAYMENT
)
from app.core.logging import get_logger
from app.db import collections as col
from app.services.cart_service import build_cart_summary, get_cart, remove_purchased_items
from app.services.order_service import (
    create_order, get_order, mark_order_paid, update_order_razorpay
)
from app.services.payment_service import create_razorpay_order, verify_payment

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
    """Select delivery address for checkout."""
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
        "step": CHECKOUT_STEP_ADDRESS,
        "address": chosen,
        "message": f"Delivery to: {chosen['line1']}, {chosen['city']}, {chosen['pincode']}. Shall I proceed to payment?",
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
        "step": CHECKOUT_STEP_ADDRESS,
        "address": address,
        "message": f"Address added: {line1}, {city}. Shall I use this for delivery?",
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


async def create_payment_tool(
    thread_id: str,
    user_id: str,
    selected_item_ids: list[str],
    address: dict,
) -> dict:
    """Create Razorpay order and return payment details."""
    cart = await get_cart(thread_id, user_id)
    all_items = cart.get("items", [])
    selected = [i for i in all_items if i["cart_item_id"] in selected_item_ids and i.get("can_buy_here")]

    if not selected:
        return {"status": "error", "message": "No purchasable items found for selected IDs."}

    subtotal = sum(float(i["price"]["value"]) * i.get("quantity", 1) for i in selected)
    currency = selected[0]["price"].get("currency", "INR")

    # Create internal order
    order_doc = await create_order(user_id, thread_id, selected, address)
    order_id = order_doc["_id"]

    # Create Razorpay order
    rz = await create_razorpay_order(order_id, user_id, subtotal, currency)
    await update_order_razorpay(order_id, rz["razorpay_order_id"])

    return {
        "status": "success",
        "step": CHECKOUT_STEP_PAYMENT,
        "order_id": order_id,
        "razorpay_order_id": rz["razorpay_order_id"],
        "razorpay_key_id": rz["key_id"],
        "amount": rz["amount"],
        "currency": currency,
        "message": (
            f"Payment session created for {currency} {subtotal:.2f}. "
            "Please complete the payment using the checkout widget. "
            f"Order ID: {order_id}"
        ),
    }


async def confirm_payment_tool(
    thread_id: str,
    user_id: str,
    razorpay_payment_id: str,
    razorpay_order_id: str,
    razorpay_signature: str,
    selected_item_ids: list[str],
) -> dict:
    """Verify payment, create order, clean up cart."""
    valid = await verify_payment(razorpay_payment_id, razorpay_order_id, razorpay_signature)
    if not valid:
        return {
            "status": "failed",
            "message": (
                "Hmm, the payment verification didn't go through. This can sometimes happen due to "
                "a network hiccup. Would you like to:\n"
                "1. Try the payment again\n"
                "2. Use a different payment method\n"
                "3. Start a fresh payment session\n\n"
                "Just let me know and I'll sort it out for you!"
            ),
        }

    # Find and update order
    order = await col.orders().find_one({"razorpay_order_id": razorpay_order_id})
    if not order:
        return {"status": "error", "message": "Order not found for this payment."}

    await mark_order_paid(order["_id"], razorpay_payment_id)

    # Remove purchased items from cart
    await remove_purchased_items(thread_id, selected_item_ids)

    return {
        "status": "success",
        "step": CHECKOUT_STEP_DONE,
        "order_id": order["_id"],
        "message": (
            f"🎉 Payment confirmed! Your order {order['_id']} has been placed. "
            "The seller will dispatch it shortly. Your cart has been updated."
        ),
    }
