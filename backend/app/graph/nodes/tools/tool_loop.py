"""Tool Loop Node — LLM-driven agent loop (max N iterations).

Handles BOTH conversational shopping AND commerce operations:
  cart management, checkout (up to address selection), marketplace switching,
  product details.

Payment (Razorpay) is fully frontend-driven — the agent does NOT create
Razorpay orders or confirm payments.  After address selection the agent
emits checkout.step="payment_required" and returns control to the frontend.
"""
import json
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.constants import (
    MAX_TOOL_ITERATIONS, TOOL_CONTEXT_MESSAGES,
    TOOL_PRODUCT_DETAIL, TOOL_SEARCH,
    TOOL_ADD_TO_CART, TOOL_REMOVE_FROM_CART, TOOL_SHOW_CART,
    TOOL_UPDATE_CART_QTY, TOOL_CLEAR_CART, TOOL_CHANGE_MARKETS,
    TOOL_START_CHECKOUT, TOOL_SELECT_ADDRESS,
    TOOL_ADD_ADDRESS, TOOL_BUY_NOW, TOOL_GET_ORDERS,
    CHECKOUT_STEP_PAYMENT_REQUIRED,
)
from app.core.llm_factory import get_llm, is_llm_configured
from app.core.logging import get_logger
from app.graph.nodes.tools.cart_tools import (
    add_to_cart_tool, clear_cart_tool, remove_from_cart_tool,
    show_cart_tool, update_cart_quantity_tool,
)
from app.graph.nodes.tools.checkout_tools import (
    add_address_tool, list_addresses_tool,
    select_address_tool, start_checkout_tool,
)
from app.graph.nodes.tools.marketplace_tool import change_marketplaces_tool
from app.graph.nodes.tools.product_tool import product_detail_tool
from app.graph.nodes.tools.search_tool import search_tool
from app.graph.state import AgentState
from app.services.order_service import get_user_orders

logger = get_logger(__name__)

TOOL_SYSTEM = """You are a friendly, conversational AI shopping assistant with full access to commerce tools. \
Your job is to help users find products, manage their cart, and guide them through checkout up to payment. \
Be warm, engaging, and guide users through each step like a knowledgeable sales assistant.

═══════════════════════════════════════════════════════
AVAILABLE TOOLS
═══════════════════════════════════════════════════════

SEARCH & PRODUCT INFO:
  product_detail — Get full details of a specific product (checks cache first, then live).
    Input: {"tool": "product_detail", "product_id": "<id>"}
    ⚠ If product_id is unknown or NOT_FOUND: fall back to search_tool immediately.

  search_tool — Search for products across active marketplaces.
    Input: {"tool": "search_tool", "query": "<query>", "update_params": {<optional filters>}}

CART MANAGEMENT:
  add_to_cart — Add a product to the cart.
    Input: {"tool": "add_to_cart", "product_id": "<id>", "quantity": <n>}
    ⚠ product_id MUST come from CURRENT PRODUCTS list. If the product is not there,
       use search_tool or product_detail first to fetch it, confirm with user, then add.
    ⚠ External products (can_buy_here=false) CAN be added to cart but CANNOT be purchased here.

  remove_from_cart — Remove a specific item from the cart.
    Input: {"tool": "remove_from_cart", "cart_item_id": "<cart_item_id>"}
    ⚠ If you don't have the cart_item_id, call show_cart first to get it.

  update_cart_quantity — Update the quantity of a cart item.
    Input: {"tool": "update_cart_quantity", "cart_item_id": "<id>", "quantity": <n>}
    ⚠ If you don't have the cart_item_id or current quantity, call show_cart first.

  show_cart — Fetch and display the current cart with all item details.
    Input: {"tool": "show_cart"}
    ⚠ Use this whenever you need cart_item_id, current quantities, or any cart info.

  clear_cart — Remove all items from the cart.
    Input: {"tool": "clear_cart"}

MARKETPLACE:
  change_marketplaces — Switch to different marketplaces.
    Input: {"tool": "change_marketplaces", "marketplaces": ["local", "ebay"]}
    Available: local, ebay, mock

CHECKOUT (Agent scope ends at address — payment is handled by the frontend widget):
  start_checkout — Begin the checkout process. Always follow the CHECKOUT FLOW below.
    Input: {"tool": "start_checkout", "cart_item_ids": null}
    ⚠ cart_item_ids is always null — checkout automatically uses all purchasable (local) items.
    ⚠ External items are listed separately and cannot be purchased here.

  select_address — Select a saved delivery address and trigger payment widget.
    Input: {"tool": "select_address", "address_id": "<id>"}
    ⚠ After this tool succeeds, ALWAYS give a final_answer — do NOT call any more tools.
       The frontend will automatically show the Razorpay payment widget.

  add_address — Save a new delivery address.
    Input: {"tool": "add_address", "line1": "...", "city": "...", "state": "...", "pincode": "...", "line2": "", "country": "India"}
    ⚠ After adding, ask user to confirm: "Shall I use this address for delivery?"
    ⚠ Then call select_address with the new address id to confirm it.

  list_addresses — List all saved delivery addresses for the user.
    Input: {"tool": "list_addresses"}
    ⚠ After showing addresses, always ask: "Would you like to use one of these, or add a new address?"

ORDERS:
  get_orders — Fetch the user's order history (recent purchases, order status, tracking).
    Input: {"tool": "get_orders"}
    Use this when user asks about: "my orders", "order status", "what did I buy", "where is my order",
    "recent purchases", any order-related question.

═══════════════════════════════════════════════════════
CHECKOUT FLOW (FOLLOW THIS EXACTLY)
═══════════════════════════════════════════════════════
When user initiates checkout:

STEP 1 — HANDLE EXTERNAL PRODUCTS:
  - Call show_cart to get current cart if you don't have it.
  - Identify any external products (can_buy_here=false).
  - If external products exist, inform user they must be purchased directly:
    "These items are from external marketplaces — visit the original site to purchase:
     • <title> — <redirect_url>"
  - Ask: "Would you like me to remove them from your cart before we continue?"
  - Wait for user response before proceeding.

STEP 2 — START CHECKOUT:
  - Call start_checkout (cart_item_ids: null — it automatically selects all purchasable items).
  - If no local items, inform user there's nothing purchasable here.

STEP 3 — SELECT DELIVERY ADDRESS:
  - Call list_addresses to show saved addresses.
  - Always ask: "Would you like to use one of these addresses, or add a new one?"
  - Let user choose or add a new address.
  - Call select_address with the chosen address_id.

STEP 4 — HAND OFF TO PAYMENT WIDGET (CRITICAL):
  - After select_address succeeds, give a final_answer IMMEDIATELY.
  - Tell the user: "A secure payment widget will appear shortly to complete your purchase 💳"
  - Do NOT call any more tools. Do NOT mention Razorpay details.
  - The frontend handles payment automatically when it sees checkout.step="payment_required".

STEP 5 — AFTER PAYMENT:
  - Payment outcome messages (success, failure, cancellation) are automatically
    injected into the conversation by the backend/frontend synchronization layer.
  - Do NOT generate payment confirmation, payment failure, or payment cancellation
    messages yourself.
  - Do NOT celebrate, apologize, or restate payment status unless the user
    explicitly asks a follow-up question about the payment or order.
  - The payment system is responsible for notifying the user and persisting
    those messages in chat history.
═══════════════════════════════════════════════════════
DECISION RULES
═══════════════════════════════════════════════════════
1. PRODUCT NOT IN CURRENT LIST:
   - User refers to a product not in CURRENT PRODUCTS → use product_detail or search_tool first.
   - Confirm the product with user ("Is this the one you meant: <title> — ₹<price>?") before adding.

2. CART ACTIONS WITHOUT IDs:
   - Need cart_item_id → call show_cart first, get the id, then proceed.
   - Need current quantity → call show_cart first.
   - Any cart question (totals, items, status) → call show_cart.

3. "SHOW ME 5 RED SHIRTS AND 5 BLUE JEANS":
   - These are two separate product types — do NOT merge into one query.
   - Search for each type separately, return combined results.
   - Preserve all requested items in filtering/ranking — do NOT filter out one category.

4. "BUY [product] FOR ME, DON'T SHOW ANYTHING":
   - Treat as silent-buy intent. Skip browsing, go directly to:
     add_to_cart → start_checkout → list_addresses → select_address.
   - Keep messages brief and progress-oriented.

5. EXTERNAL PRODUCTS IN CART:
   - Adding external to cart is fine. Inform user with a note: "Note: this is an external product — \
you'll need to purchase it directly on the seller's site."
   - At checkout time: list them with redirect URLs, handle per CHECKOUT FLOW above.

6. PRODUCT REFERENCE RESOLUTION:
   - "first product" / "second product" = CURRENT PRODUCTS[0] / [1] by index.
   - "the red shirt I saw earlier" = search in CURRENT PRODUCTS by title/description.
   - "cart item 2" = second item in CART (use show_cart if needed).
   - If product reference is ambiguous or not found → search or ask user to clarify.

7. ALWAYS CONFIRM CRITICAL ACTIONS:
   - Before buying, adding to cart, or removing items when the product isn't clearly identified.
   - Exception: user explicitly says "don't ask, just buy" or similar.
8. PAYMENT IS HANDLED BY FRONTEND — NEVER by you:
   - Do NOT ask for card details, UPI IDs, or payment information.
   - Do NOT mention Razorpay order IDs or payment links.
   - After address confirmation, simply tell the user the payment widget will appear.
   - Payment success, failure, and cancellation messages are automatically injected
     into the chat and persisted by the payment system.
   - Do NOT generate those payment outcome messages yourself.
═══════════════════════════════════════════════════════
ENGAGEMENT GUIDELINES
═══════════════════════════════════════════════════════
- Use short, friendly transition messages between steps:
  "Great choice! Now let me find your saved addresses... 📦"
  "Perfect, address confirmed! The payment widget will appear now 💳"
  "All done! Your order is on its way 🎉"
- After listing addresses, always ask if user wants to add a new one.
- After checkout starts, keep user informed of each step.
- If something fails, offer clear alternatives (retry, different option, get help).

═══════════════════════════════════════════════════════
FINAL ANSWER FORMAT
═══════════════════════════════════════════════════════
{
  "action": "final_answer",
  "tool": null,
  "tool_input": null,
  "response": "<friendly message to user>",
  "product_indices": [<optional 0-based indexes from CURRENT PRODUCTS to display>],
  "external_item_indices": [<optional 0-based indexes from CURRENT EXTERNAL ITEMS to show as redirect links>],
  "commerce_update": {
    "selected_marketplaces": null,
    "checkout_step": null,
    "checkout_data": null
  }
}

Rules for product_indices and external_item_indices:
- Include product_indices ONLY when the user asked to see products (search results, product details).
- Include external_item_indices ONLY when the response is specifically about checkout/cart external items.
- For cart/checkout responses where external items are relevant: set external_item_indices to list their 0-based positions in CURRENT EXTERNAL ITEMS.
- Do NOT include product_indices or external_item_indices for purely conversational replies (greetings, cart updates without listing items, address selection, payment steps).
- CURRENT EXTERNAL ITEMS are provided below the products list when available.

ALWAYS respond with valid JSON only — no markdown fences, no extra text."""


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

    # Surface external items from the most recent tool message so LLM can reference them
    current_external_items = _extract_recent_external_items(messages)
    external_json = json.dumps(current_external_items, indent=2) if current_external_items else "none"

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

CURRENT EXTERNAL ITEMS (from last tool — include external_item_indices in final_answer if relevant):
{external_json}

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

        # If LLM gave no product_indices but last tool was a search — use all current products
        last_tool = tool_ctx.get("last_tool_used", "")
        if not selected_products and last_tool in (TOOL_SEARCH, TOOL_PRODUCT_DETAIL):
            selected_products = current_products

        # Resolve external items the LLM explicitly selected via external_item_indices.
        external_item_indices = decision.get("external_item_indices") or []
        selected_external = [
            current_external_items[i]
            for i in external_item_indices
            if 0 <= i < len(current_external_items)
        ]
        # Auto-carry external items after start_checkout
        has_external = bool(selected_external)
        if not selected_external and last_tool == TOOL_START_CHECKOUT and current_external_items:
            selected_external = current_external_items
            has_external = True

        commerce_update = decision.get("commerce_update") or {}
        logger.info("Node: tool_loop — final answer")
        return _final_answer_state(
            response_text, tool_ctx, state, selected_products,
            commerce_update, selected_external, has_external
        )

    # ── Execute tool ──────────────────────────────────────────────────────────
    tool_name = decision.get("tool")
    tool_input = decision.get("tool_input") or {}
    thread_id = state.get("thread_id", "")
    user_id = state.get("user_id", "")

    logger.info("Node: tool_loop — calling tool", extra={"tool": tool_name, "input": tool_input})

    tool_result, extra_state = await _dispatch_tool(
        tool_name, tool_input, state, current_products, cart_items,
        thread_id, user_id
    )

    tool_result_msg = _format_tool_result(tool_name, tool_result)
    tool_products = _extract_products_from_result(tool_name, tool_result)

    tool_external_items = _extract_external_items_from_result(tool_name, tool_result)
    has_external = tool_result.get("has_external", False)

    tool_ctx["iteration"] = iteration + 1
    tool_ctx["action"] = "call_tool"
    tool_ctx["last_tool_used"] = tool_name or ""
    tool_ctx["last_tool_status"] = tool_result.get("status", "unknown")

    messages_update = [{
        "role": "tool",
        "content": tool_result_msg,
        "products": tool_products,
        "external_items": tool_external_items,
        "has_external": has_external,
    }]

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
        cart_summary = result.get("cart_summary") or {}
        if cart_summary:
            extra["thread_cart"] = {"items": cart_summary.get("items", [])}
            if cart_summary.get("external_items"):
                extra["_cart_external_items"] = cart_summary["external_items"]
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
        result = await start_checkout_tool(thread_id, user_id, None)
        if result.get("status") in ("success", "external_only"):
            current_checkout = dict(state.get("checkout") or {})
            current_checkout.update({
                "active": True,
                "step": result.get("step"),
                "selected_cart_items": result.get("selected_item_ids", []),
                "external_items": result.get("external_items", []),
                "has_external": result.get("has_external", False),
            })
            extra["checkout"] = current_checkout
        return result, extra

    if tool_name == "list_addresses":
        result = await list_addresses_tool(user_id)
        return result, extra

    if tool_name == TOOL_SELECT_ADDRESS:
        address_id = tool_input.get("address_id", "")
        result = await select_address_tool(user_id, address_id)
        if result.get("status") == "success":
            current_checkout = dict(state.get("checkout") or {})
            current_checkout.update({
                # step is now CHECKOUT_STEP_PAYMENT_REQUIRED ("payment_required")
                "step": result.get("step", CHECKOUT_STEP_PAYMENT_REQUIRED),
                "selected_address_id": address_id,
                # Store full address object so REST /checkout/payment can use it
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

    if tool_name == TOOL_BUY_NOW:
        pid = tool_input.get("product_id", "")
        product = _resolve_product(pid, current_products)
        if not product:
            return {"status": "error", "message": f"Product '{pid}' not found."}, extra
        await add_to_cart_tool(product, thread_id, user_id, 1)
        result = await start_checkout_tool(thread_id, user_id, None)
        if result.get("status") in ("success", "external_only"):
            current_checkout = dict(state.get("checkout") or {})
            current_checkout.update({
                "active": True,
                "step": result.get("step"),
                "selected_cart_items": result.get("selected_item_ids", []),
                "external_items": result.get("external_items", []),
                "has_external": result.get("has_external", False),
            })
            extra["checkout"] = current_checkout
        return result, extra

    if tool_name == TOOL_GET_ORDERS:
        try:
            orders = await get_user_orders(user_id)
            if not orders:
                return {"status": "success", "orders": [], "message": "You have no orders yet."}, extra
            lines = []
            for o in orders[:10]:
                lines.append(
                    f"• Order {o['_id']} | Status: {o['status']} | "
                    f"Total: {o.get('currency','INR')} {o.get('total',0)} | "
                    f"Items: {len(o.get('items', []))}"
                )
            return {
                "status": "success",
                "orders": orders[:10],
                "message": "Your recent orders:\n" + "\n".join(lines),
            }, extra
        except Exception as exc:
            return {"status": "error", "message": str(exc)}, extra

    logger.warning("Unknown tool requested", extra={"tool": tool_name})
    return {"status": "error", "message": f"Unknown tool: {tool_name}"}, extra


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_recent_products(messages: list) -> list[dict]:
    for msg in reversed(messages):
        products = msg.get("products") if isinstance(msg, dict) else []
        if products:
            return products
    return []


def _extract_recent_external_items(messages: list) -> list[dict]:
    """Return external_items from the most recent tool message that has them.
    Only looks at tool messages so we don't accidentally pick up stale assistant data."""
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "")
        if role == "tool" and msg.get("external_items"):
            return msg["external_items"]
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
    """Build a concise text summary of the tool result for the LLM context."""
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
        currency = cart.get("currency", "INR")
        lines.append(f"Subtotal (local items): {currency} {cart.get('estimated_total', 0)}")
        ext_count = cart.get("external_count", 0)
        if ext_count:
            lines.append(f"Note: {ext_count} external item(s) must be purchased on their original site.")
        return "\n".join(lines)

    if tool_name == TOOL_CHANGE_MARKETS:
        return message or f"Marketplaces updated: {result.get('selected_marketplaces', [])}"

    if tool_name == TOOL_START_CHECKOUT:
        parts = [message or f"Checkout: {status}"]
        selected = result.get("selected_items", [])
        if selected:
            parts.append(f"Proceeding with {len(selected)} purchasable item(s).")
        external_notice = result.get("external_notice", "")
        if external_notice:
            parts.append(external_notice)
        return "\n".join(parts)

    if tool_name in (TOOL_SELECT_ADDRESS, TOOL_ADD_ADDRESS):
        return message or f"Checkout: {status}"

    return message or f"Tool {tool_name}: {status}"


def _extract_products_from_result(tool_name: str, result: dict) -> list[dict]:
    """Extract local/purchasable products from tool result for the message products field."""
    if tool_name == TOOL_PRODUCT_DETAIL and result.get("status") == "found":
        p = result.get("product")
        return [p] if p else []
    if tool_name == TOOL_SEARCH and result.get("status") == "success":
        return result.get("results", [])
    if tool_name == TOOL_START_CHECKOUT and result.get("status") in ("success",):
        return result.get("selected_items", [])
    return []


def _extract_external_items_from_result(tool_name: str, result: dict) -> list[dict]:
    """
    Extract external (non-purchasable) items from tool result.
    These are surfaced separately to the frontend so it can render
    redirect links with full details (image, price, title, url).
    """
    if tool_name == TOOL_START_CHECKOUT:
        raw_external = result.get("external_items", [])
        enriched = []
        for item in raw_external:
            enriched.append({
                "cart_item_id": item.get("cart_item_id", ""),
                "title": item.get("title", ""),
                "redirect_url": item.get("redirect_url", ""),
                "image": item.get("image", ""),
                "price": item.get("price", {}),
                "source": item.get("source", "external"),
                "can_buy_here": False,
            })
        return enriched
    if tool_name == TOOL_SHOW_CART:
        cart = result.get("cart_summary", {})
        external = cart.get("external_items", [])
        return [
            {
                "cart_item_id": item.get("cart_item_id", ""),
                "title": item.get("title", ""),
                "redirect_url": item.get("redirect_url", item.get("url", "")),
                "image": item.get("image", ""),
                "price": item.get("price", {}),
                "source": item.get("source", "external"),
                "can_buy_here": False,
            }
            for item in external
        ]
    return []


def _final_answer_state(
    text: str,
    tool_ctx: dict,
    state: AgentState,
    products: Optional[list[dict]] = None,
    commerce_update: Optional[dict] = None,
    external_items: Optional[list[dict]] = None,
    has_external: bool = False,
) -> dict:
    """Build the state update for a final assistant answer.

    The assistant message carries products AND external_items so that
    search_service can read everything it needs from the single last assistant
    message without scanning backwards through tool messages.
    """
    result: dict = {
        "tool_context": {**tool_ctx, "iteration": MAX_TOOL_ITERATIONS, "action": "final_answer"},
        "messages": [{
            "role": "assistant",
            "content": text,
            "products": products or [],
            "external_items": external_items or [],
            "has_external": has_external,
        }],
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
