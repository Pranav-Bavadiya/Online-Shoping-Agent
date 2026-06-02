"""Tool Loop Node — LLM-driven agent loop (max 3 iterations).

Handles BOTH conversational shopping AND all commerce operations:
  cart management, checkout, marketplace switching, product details.
"""
import json
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.constants import (
    MAX_TOOL_ITERATIONS, TOOL_CONTEXT_MESSAGES,
    TOOL_PRODUCT_DETAIL, TOOL_SEARCH,
    TOOL_ADD_TO_CART, TOOL_REMOVE_FROM_CART, TOOL_SHOW_CART,
    TOOL_UPDATE_CART_QTY, TOOL_CLEAR_CART, TOOL_CHANGE_MARKETS,
    TOOL_START_CHECKOUT, TOOL_SELECT_ITEMS, TOOL_SELECT_ADDRESS,
    TOOL_ADD_ADDRESS, TOOL_CREATE_PAYMENT, TOOL_CONFIRM_PAYMENT,
    TOOL_BUY_NOW,
)
from app.core.llm_factory import get_llm, is_llm_configured
from app.core.logging import get_logger
from app.graph.nodes.tools.cart_tools import (
    add_to_cart_tool, clear_cart_tool, remove_from_cart_tool,
    show_cart_tool, update_cart_quantity_tool,
)
from app.graph.nodes.tools.checkout_tools import (
    add_address_tool, confirm_payment_tool, create_payment_tool,
    list_addresses_tool, select_address_tool, start_checkout_tool,
)
from app.graph.nodes.tools.marketplace_tool import change_marketplaces_tool
from app.graph.nodes.tools.product_tool import product_detail_tool
from app.graph.nodes.tools.search_tool import search_tool
from app.graph.state import AgentState

logger = get_logger(__name__)

TOOL_SYSTEM = """You are a conversational AI shopping assistant with access to commerce tools.

AVAILABLE TOOLS
===============
SEARCH & PRODUCT DETAILS:
  product_detail  — Get details of a product shown to user (from cache first).
    Input: {"tool": "product_detail", "product_id": "<id>"}

  search_tool — Live product search across selected marketplaces.
    Input: {"tool": "search_tool", "query": "<query>", "update_params": {<optional>}}

CART MANAGEMENT:
  add_to_cart — Add a product to the thread cart.
    Input: {"tool": "add_to_cart", "product_id": "<id>", "quantity": 1}
    Note: product_id must be from CURRENT PRODUCTS list.

  remove_from_cart — Remove a cart item.
    Input: {"tool": "remove_from_cart", "cart_item_id": "<cart_item_id>"}

  show_cart — Show the current cart contents.
    Input: {"tool": "show_cart"}

  update_cart_quantity — Change quantity of a cart item.
    Input: {"tool": "update_cart_quantity", "cart_item_id": "<id>", "quantity": <n>}

  clear_cart — Empty the entire cart.
    Input: {"tool": "clear_cart"}

MARKETPLACE:
  change_marketplaces — Switch the active marketplaces.
    Input: {"tool": "change_marketplaces", "marketplaces": ["local", "ebay"]}
    Available: local, ebay, mock

CHECKOUT:
  start_checkout — Begin checkout for cart items.
    Input: {"tool": "start_checkout", "cart_item_ids": ["<id>", ...] or null (= all)}

  select_address — Choose delivery address by address_id.
    Input: {"tool": "select_address", "address_id": "<id>"}

  add_address — Add a new delivery address.
    Input: {"tool": "add_address", "line1": "...", "city": "...", "state": "...", "pincode": "...", "line2": "", "country": "India"}

  list_addresses — Show user's saved addresses.
    Input: {"tool": "list_addresses"}

  create_payment — Create Razorpay payment session.
    Input: {"tool": "create_payment", "selected_item_ids": [...], "address_id": "<id>"}

  confirm_payment — Verify payment and create order.
    Input: {"tool": "confirm_payment", "razorpay_payment_id": "...", "razorpay_order_id": "...", "razorpay_signature": "..."}

DECISION RULES
==============
- product details request → use product_detail first; if NOT_FOUND → search_tool
- "add [product] to cart" → resolve product from CURRENT PRODUCTS then add_to_cart
- "remove [item]" → show_cart first if you need cart_item_id, then remove_from_cart
- "show/view cart" → show_cart
- "buy/checkout/purchase" → start_checkout (ask clarification if ambiguous which items)
- Mixed cart (local + external): explain external items will be redirect-only
- "use Amazon/eBay/local" → change_marketplaces
- payment confirmation → confirm_payment
- All other questions → final_answer using conversation context and current products

CART REFERENCE RESOLUTION:
- "first product" = CURRENT PRODUCTS[0], "second product" = CURRENT PRODUCTS[1], etc.
- "the headphones" = find by name in CURRENT PRODUCTS
- "cart item 1/2/3" = by position in CART (use show_cart to get ids if needed)

EXTERNAL PRODUCT RULE:
- If user tries to buy an external product (Amazon/eBay, can_buy_here=false), explain it cannot
  be purchased internally and provide the redirect URL.

FINAL ANSWER FORMAT:
{
  "action": "final_answer",
  "tool": null,
  "tool_input": null,
  "response": "<friendly message>",
  "product_indices": [<optional 0-based indexes from CURRENT PRODUCTS>],
  "commerce_update": {
    "selected_marketplaces": null,  // set if marketplaces changed
    "checkout_step": null,           // set during checkout flow
    "checkout_data": null            // set during checkout flow
  }
}

ALWAYS respond with valid JSON (no markdown fences)."""


async def tool_loop_node(state: AgentState) -> dict:
    logger.info("Node: tool_loop start", extra={"request_id": state.get("request_id")})

    tool_ctx = dict(state.get("tool_context") or {})
    iteration = int(tool_ctx.get("iteration") or 0)
    tool_ctx["iteration"] = iteration

    # ── Iteration limit ───────────────────────────────────────────────────────
    if iteration >= MAX_TOOL_ITERATIONS:
        logger.info("Node: tool_loop — max iterations reached")
        return _final_answer_state(
            "Sorry, I wasn't able to complete your request after several attempts. "
            "Please try rephrasing or searching with different terms.",
            tool_ctx, state
        )

    # ── Build context ─────────────────────────────────────────────────────────
    messages = state.get("messages", [])
    context_msgs = messages[-(TOOL_CONTEXT_MESSAGES):]
    context_str = "\n".join(
        f"{(m.get('role') if isinstance(m, dict) else getattr(m, 'type', 'unknown'))}: "
        f"{(m.get('content') if isinstance(m, dict) else getattr(m, 'content', ''))}"
        for m in context_msgs
    )

    current_products = _extract_recent_products(messages)
    products_json = json.dumps(current_products[:20], indent=2) if current_products else "none"

    thread_cart = state.get("thread_cart") or {}
    cart_items = thread_cart.get("items", [])
    cart_json = json.dumps(cart_items[:], indent=2) if cart_items else "none"

    selected_markets = state.get("selected_marketplaces") or ["local", "ebay"]
    checkout = state.get("checkout") or {}
    conv_ctx = state.get("conversation_context") or {}

    prompt = f"""Conversation history:
{context_str}

CURRENT PRODUCTS shown to user:
{products_json}

CURRENT CART:
{cart_json}

Selected marketplaces: {selected_markets}
Checkout state: {json.dumps(checkout)}
Last product seen: {conv_ctx.get("last_product_id", "none")}
Current iteration: {iteration + 1}/{MAX_TOOL_ITERATIONS}

Decide next action:"""

    # ── No LLM configured ─────────────────────────────────────────────────────
    if not is_llm_configured():
        logger.warning("No LLM configured — tool loop fallback")
        return _final_answer_state("I can help with shopping! What are you looking for?", tool_ctx, state)

    # ── LLM decision ──────────────────────────────────────────────────────────
    try:
        llm = get_llm(temperature=0)
        resp = await llm.ainvoke([SystemMessage(content=TOOL_SYSTEM), HumanMessage(content=prompt)])
        raw = resp.content.strip().strip("```json").strip("```").strip()
        decision = json.loads(raw)
    except Exception as exc:
        logger.error("Tool loop LLM failed", extra={"error": str(exc)})
        return _final_answer_state("Sorry, I ran into an issue. Please try again.", tool_ctx, state)

    action = decision.get("action", "final_answer")

    if action == "final_answer":
        response_text = decision.get("response") or "How can I help?"
        product_indices = decision.get("product_indices") or []
        selected_products = [current_products[i] for i in product_indices if 0 <= i < len(current_products)]
        commerce_update = decision.get("commerce_update") or {}
        logger.info("Node: tool_loop — final answer")
        return _final_answer_state(response_text, tool_ctx, state, selected_products, commerce_update)

    # ── Execute tool ──────────────────────────────────────────────────────────
    tool_name = decision.get("tool")
    tool_input = decision.get("tool_input") or {}
    thread_id = state.get("thread_id", "")
    user_id = state.get("user_id", "")
    tool_result: dict[str, Any] = {}

    logger.info("Node: tool_loop — calling tool", extra={"tool": tool_name, "input": tool_input})

    tool_result, extra_state = await _dispatch_tool(
        tool_name, tool_input, state, current_products, cart_items,
        thread_id, user_id
    )

    tool_result_msg = _format_tool_result(tool_name, tool_result)
    tool_products = _extract_products_from_result(tool_name, tool_result)

    tool_ctx["iteration"] = iteration + 1
    tool_ctx["action"] = "call_tool"
    tool_ctx["last_tool_used"] = tool_name or ""
    tool_ctx["last_tool_status"] = tool_result.get("status", "unknown")

    messages_update = [{"role": "tool", "content": tool_result_msg, "products": tool_products}]

    result = {"tool_context": tool_ctx, "messages": messages_update}
    result.update(extra_state)
    return result


# ── Tool dispatcher ───────────────────────────────────────────────────────────

async def _dispatch_tool(
    tool_name: str,
    tool_input: dict,
    state: AgentState,
    current_products: list[dict],
    cart_items: list[dict],
    thread_id: str,
    user_id: str,
) -> tuple[dict, dict]:
    """Execute the chosen tool. Returns (tool_result, extra_state_updates)."""
    extra: dict = {}
    tool_ctx = dict(state.get("tool_context") or {})

    if tool_name == TOOL_PRODUCT_DETAIL:
        pid = tool_input.get("product_id", "")
        result = await product_detail_tool(pid)
        if result.get("status") == "NOT_FOUND":
            query = _build_fallback_query(pid, current_products)
            result = await search_tool(query, state.get("structured_query"))
        return result, extra

    if tool_name == TOOL_SEARCH:
        query = tool_input.get("query", "")
        update_params = tool_input.get("update_params") or {}
        sq = dict(state.get("structured_query") or {})
        if update_params:
            sq.update(update_params)
        # Filter by selected marketplaces
        markets = state.get("selected_marketplaces") or ["local", "ebay"]
        sq["selected_marketplaces"] = markets
        result = await search_tool(query, sq)
        return result, extra

    if tool_name == TOOL_ADD_TO_CART:
        pid = tool_input.get("product_id", "")
        qty = int(tool_input.get("quantity", 1))
        product = _resolve_product(pid, current_products)
        if not product:
            return {"status": "error", "message": f"Product '{pid}' not found in current results."}, extra
        result = await add_to_cart_tool(product, thread_id, user_id, qty)
        if result.get("status") == "success":
            cart = result.get("cart_summary", {})
            extra["thread_cart"] = {"items": cart.get("items", [])}
        return result, extra

    if tool_name == TOOL_REMOVE_FROM_CART:
        cart_item_id = tool_input.get("cart_item_id", "")
        result = await remove_from_cart_tool(cart_item_id, thread_id, user_id)
        if result.get("status") == "success":
            cart = result.get("cart_summary", {})
            extra["thread_cart"] = {"items": cart.get("items", [])}
        return result, extra

    if tool_name == TOOL_SHOW_CART:
        result = await show_cart_tool(thread_id, user_id)
        if result.get("cart_summary"):
            extra["thread_cart"] = {"items": result["cart_summary"].get("items", [])}
        return result, extra

    if tool_name == TOOL_UPDATE_CART_QTY:
        result = await update_cart_quantity_tool(
            tool_input.get("cart_item_id", ""),
            int(tool_input.get("quantity", 1)),
            thread_id, user_id
        )
        if result.get("status") == "success":
            extra["thread_cart"] = {"items": result["cart_summary"].get("items", [])}
        return result, extra

    if tool_name == TOOL_CLEAR_CART:
        result = await clear_cart_tool(thread_id, user_id)
        extra["thread_cart"] = {"items": []}
        return result, extra

    if tool_name == TOOL_CHANGE_MARKETS:
        markets = tool_input.get("marketplaces", [])
        result = await change_marketplaces_tool(markets)
        if result.get("status") == "success":
            extra["selected_marketplaces"] = result["selected_marketplaces"]
        return result, extra

    if tool_name == TOOL_START_CHECKOUT:
        ids = tool_input.get("cart_item_ids")  # None = all
        result = await start_checkout_tool(thread_id, user_id, ids)
        if result.get("status") in ("success", "external_only"):
            current_checkout = dict(state.get("checkout") or {})
            current_checkout.update({
                "active": True,
                "step": result.get("step"),
                "selected_cart_items": result.get("selected_item_ids", []),
            })
            extra["checkout"] = current_checkout
        return result, extra

    if tool_name == "list_addresses":
        result = await list_addresses_tool(user_id)
        return result, extra

    if tool_name == TOOL_SELECT_ADDRESS:
        result = await select_address_tool(user_id, tool_input.get("address_id", ""))
        if result.get("status") == "success":
            current_checkout = dict(state.get("checkout") or {})
            current_checkout.update({
                "step": result.get("step"),
                "selected_address_id": tool_input.get("address_id"),
                "_selected_address": result.get("address"),
            })
            extra["checkout"] = current_checkout
        return result, extra

    if tool_name == TOOL_ADD_ADDRESS:
        result = await add_address_tool(
            user_id,
            tool_input.get("line1", ""), tool_input.get("city", ""),
            tool_input.get("state", ""), tool_input.get("pincode", ""),
            tool_input.get("line2", ""), tool_input.get("country", "India"),
        )
        if result.get("status") == "success":
            current_checkout = dict(state.get("checkout") or {})
            current_checkout["_selected_address"] = result.get("address")
            current_checkout["step"] = result.get("step")
            extra["checkout"] = current_checkout
        return result, extra

    if tool_name == TOOL_CREATE_PAYMENT:
        current_checkout = dict(state.get("checkout") or {})
        selected_ids = current_checkout.get("selected_cart_items", [])
        address = current_checkout.get("_selected_address") or {}

        if not selected_ids:
            return {"status": "error", "message": "No checkout items selected. Please start checkout first."}, extra
        if not address:
            address_id = current_checkout.get("selected_address_id", "")
            if address_id:
                addr_res = await select_address_tool(user_id, address_id)
                address = addr_res.get("address", {})
        if not address:
            return {"status": "error", "message": "No delivery address selected. Please select an address first."}, extra

        result = await create_payment_tool(thread_id, user_id, selected_ids, address)
        if result.get("status") == "success":
            current_checkout.update({
                "step": result.get("step"),
                "current_order_id": result.get("order_id"),
                "razorpay_order_id": result.get("razorpay_order_id"),
                "payment_link": result.get("razorpay_order_id"),
            })
            extra["checkout"] = current_checkout
        return result, extra

    if tool_name == TOOL_CONFIRM_PAYMENT:
        current_checkout = dict(state.get("checkout") or {})
        selected_ids = current_checkout.get("selected_cart_items", [])
        result = await confirm_payment_tool(
            thread_id, user_id,
            tool_input.get("razorpay_payment_id", ""),
            tool_input.get("razorpay_order_id", ""),
            tool_input.get("razorpay_signature", ""),
            selected_ids,
        )
        if result.get("status") == "success":
            # Reset checkout state, update cart
            extra["checkout"] = {
                "active": False, "step": "done",
                "selected_cart_items": [], "selected_address_id": None,
                "payment_status": "captured", "current_order_id": result.get("order_id"),
            }
            # Reflect cart update in state
            from app.services.cart_service import get_cart, build_cart_summary
            cart = await get_cart(thread_id, user_id)
            extra["thread_cart"] = {"items": cart.get("items", [])}
        return result, extra

    if tool_name == TOOL_BUY_NOW:
        # Quick add-to-cart + start-checkout shortcut
        pid = tool_input.get("product_id", "")
        product = _resolve_product(pid, current_products)
        if not product:
            return {"status": "error", "message": f"Product '{pid}' not found."}, extra
        await add_to_cart_tool(product, thread_id, user_id, 1)
        result = await start_checkout_tool(thread_id, user_id, None)
        return result, extra

    logger.warning("Unknown tool requested", extra={"tool": tool_name})
    return {"status": "error", "message": f"Unknown tool: {tool_name}"}, extra


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_recent_products(messages: list) -> list[dict]:
    for msg in reversed(messages):
        products = msg.get("products") if isinstance(msg, dict) else []
        if products:
            return products
    return []


def _resolve_product(product_id: str, current_products: list[dict]) -> Optional[dict]:
    """Find a product by id or partial title match in current_products."""
    for p in current_products:
        if p.get("product_id") == product_id:
            return p
    return None


def _build_fallback_query(product_id: str, current_products: list[dict]) -> str:
    for p in current_products:
        if p.get("product_id") == product_id:
            return p.get("title", product_id)
    return product_id


def _format_tool_result(tool_name: str, result: dict) -> str:
    status = result.get("status", "unknown")
    message = result.get("message", "")

    if tool_name == TOOL_PRODUCT_DETAIL and status == "found":
        p = result.get("product", {})
        pr = p.get("price") or {}
        return (f"Product: {p.get('title','?')} | Price: {pr.get('currency','INR')} "
                f"{pr.get('value',0)} | Rating: {p.get('rating',0)}/5")

    if tool_name == TOOL_SEARCH and status == "success":
        results = result.get("results", [])
        if results:
            lines = [f"Found {len(results)} products:"]
            for i, p in enumerate(results[:5], 1):
                pr = p.get("price") or {}
                lines.append(f"{i}. {p.get('title','?')} — {pr.get('currency','INR')} {pr.get('value',0)}")
            return "\n".join(lines)
        return "No products found."

    if tool_name in (TOOL_ADD_TO_CART, TOOL_REMOVE_FROM_CART, TOOL_UPDATE_CART_QTY, TOOL_CLEAR_CART):
        cart = result.get("cart_summary", {})
        items = cart.get("items", [])
        return f"{message} Cart has {len(items)} item(s)."

    if tool_name == TOOL_SHOW_CART:
        cart = result.get("cart_summary", {})
        items = cart.get("items", [])
        if not items:
            return "Cart is empty."
        lines = [f"Cart ({len(items)} items):"]
        for i, item in enumerate(items, 1):
            pr = item.get("price") or {}
            flag = "✓ Purchasable here" if item.get("can_buy_here") else "↗ External"
            lines.append(f"{i}. {item.get('title','?')} x{item.get('quantity',1)} — "
                         f"{pr.get('currency','INR')} {pr.get('value',0)} [{flag}]")
        lines.append(f"Subtotal (local): {cart.get('currency','INR')} {cart.get('estimated_total',0)}")
        return "\n".join(lines)

    if tool_name == TOOL_CHANGE_MARKETS:
        return message or f"Marketplaces updated: {result.get('selected_marketplaces', [])}"

    if tool_name in (TOOL_START_CHECKOUT, TOOL_SELECT_ADDRESS, TOOL_ADD_ADDRESS,
                     TOOL_CREATE_PAYMENT, TOOL_CONFIRM_PAYMENT):
        return message or f"Checkout: {status}"

    return message or f"Tool {tool_name}: {status}"


def _extract_products_from_result(tool_name: str, result: dict) -> list[dict]:
    if tool_name == TOOL_PRODUCT_DETAIL and result.get("status") == "found":
        p = result.get("product")
        return [p] if p else []
    if tool_name == TOOL_SEARCH and result.get("status") == "success":
        return result.get("results", [])
    return []


def _final_answer_state(
    text: str,
    tool_ctx: dict,
    state: AgentState,
    products: Optional[list[dict]] = None,
    commerce_update: Optional[dict] = None,
) -> dict:
    result: dict = {
        "tool_context": {**tool_ctx, "iteration": MAX_TOOL_ITERATIONS, "action": "final_answer"},
        "messages": [{"role": "assistant", "content": text, "products": products or []}],
        "final_products": products or [],
    }
    if commerce_update:
        if commerce_update.get("selected_marketplaces"):
            result["selected_marketplaces"] = commerce_update["selected_marketplaces"]
        if commerce_update.get("checkout_step"):
            existing = dict(state.get("checkout") or {})
            existing["step"] = commerce_update["checkout_step"]
            if commerce_update.get("checkout_data"):
                existing.update(commerce_update["checkout_data"])
            result["checkout"] = existing
    return result


def should_continue_tool_loop(state: AgentState) -> str:
    tool_ctx = state.get("tool_context") or {}
    iteration = int(tool_ctx.get("iteration") or 0)
    action = tool_ctx.get("action", "")
    if action == "final_answer":
        return "done"
    if iteration >= MAX_TOOL_ITERATIONS:
        return "done"
    return "loop"
