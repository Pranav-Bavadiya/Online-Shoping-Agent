"""Tool Loop Node — LLM-driven agent loop for chat intent (max 3 iterations).

Key behaviours
--------------
1. Smart tool selection: prefers product_detail (cache) when user asks about an
   already-seen product; falls back to search_tool if product not found in cache.
2. Iteration limit: returns a friendly "unable to find" message instead of
   a generic filler.
3. Products context: last displayed products are injected into every LLM call
   so the model can answer follow-up questions without a new API call.
4. Raw product data: full structured product JSON is stored in tool_context and
   passed back to the LLM so it can reference exact field values.
"""
import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.constants import MAX_TOOL_ITERATIONS, TOOL_CONTEXT_MESSAGES, TOOL_PRODUCT_DETAIL, TOOL_SEARCH
from app.core.llm_factory import get_llm, is_llm_configured
from app.core.logging import get_logger
from app.graph.nodes.tools.product_tool import product_detail_tool
from app.graph.nodes.tools.search_tool import search_tool
from app.graph.state import AgentState

logger = get_logger(__name__)

TOOL_SYSTEM = """You are a helpful AI shopping assistant with access to tools.

Available tools:
1. product_detail — Fetch full details about a product that was ALREADY shown to the user.
   Use this FIRST when the user asks for more details, specs, or anything about a product
   they have already seen. This reads from cache (fast, no API cost).
   Input: {"tool": "product_detail", "product_id": "<id>"}

2. search_tool — Search for products via the live API.
   Use this when:
     • The user wants NEW products not yet shown or user want more details for a product.
     • product_detail returned NOT_FOUND for the requested product.
     • The user asks to refine/change the current search.
   Input: {"tool": "search_tool", "query": "<search query>", "update_params": {<optional structured overrides>}}

Decision guide:
- User asks "tell me more about [product name]" AND that product is in the CURRENT PRODUCTS list
    → use product_detail with its product_id
- product_detail returns NOT_FOUND → immediately retry with search_tool
- User says "show me more", "I want cheaper ones", "filter by brand X" → use search_tool
- You already have enough information to answer directly → use final_answer
- If you have used every tool and still don't have a good answer, give your best final_answer anyway instead of looping endlessly.
- If user ask same question again and again and you have already tried all tools, give a friendly final_answer saying you can't find it instead of looping endlessly.

Final Answer Response:
- When responding with final_answer, decide if the user needs to see specific products.
- If yes, include "product_indices" (0-based indexes of products from CURRENT PRODUCTS list).
- If no products need to be shown, leave "product_indices" empty or omit it.
- Example: User asks "what's the cheapest?", and product 0 is cheapest → include [0]
- Example: User asks "what brand is better?", no products needed → omit or []

ALWAYS respond with valid JSON (no markdown fences):
{
  "action": "call_tool" | "final_answer",
  "tool": "<tool_name or null>",
  "tool_input": {<tool params or null>},
  "response": "<final answer if action is final_answer, else null>",
  "product_indices": [<optional 0-based indexes of products to display>]
}"""


async def tool_loop_node(state: AgentState) -> dict:
    logger.info("Node: tool_loop start", extra={"request_id": state.get("request_id")})

    tool_ctx = dict(state.get("tool_context") or {})
    iteration = int(tool_ctx.get("iteration") or 0)
    tool_ctx["iteration"] = iteration

    # ── Iteration limit exceeded ─────────────────────────────────────────────
    if iteration >= MAX_TOOL_ITERATIONS:
        logger.info("Node: tool_loop — max iterations reached", extra={"request_id": state.get("request_id")})
        final_response = (
            "Sorry, I wasn't able to find what you're looking for after several attempts. "
            "Please try rephrasing your query or searching with different terms."
        )
        return _final_answer_state(final_response, tool_ctx)

    # ── Build conversation context string ────────────────────────────────────
    messages = state.get("messages", [])
    context_msgs = messages[-(TOOL_CONTEXT_MESSAGES):]
    context_str = "\n".join(
        f"{(m.get('role') if isinstance(m, dict) else getattr(m, 'type', 'unknown'))}: "
        f"{(m.get('content') if isinstance(m, dict) else getattr(m, 'content', ''))}"
        for m in context_msgs
    )

    # ── Gather current products (issue #3: pass products to LLM) ─────────────
    current_products = _extract_recent_products(messages)
    products_json = json.dumps(current_products[:20], indent=2) if current_products else "none"

    conv_ctx = state.get("conversation_context") or {}
    tc_info = json.dumps(tool_ctx)

    prompt = f"""Conversation history:
{context_str}

CURRENT PRODUCTS shown to user:
{products_json}

Tool context: {tc_info}
Last product seen: {conv_ctx.get("last_product_id", "none")}
Last category: {conv_ctx.get("last_category", "none")}
Current iteration: {iteration + 1}/{MAX_TOOL_ITERATIONS}

Decide next action:"""

    # ── No LLM configured — simple fallback ──────────────────────────────────
    if not is_llm_configured():
        logger.warning("No LLM configured — tool loop using fallback response")
        return _final_answer_state(
            "I can help you find products. Please tell me what you're looking for!", tool_ctx
        )

    # ── LLM decision ─────────────────────────────────────────────────────────
    try:
        llm = get_llm(temperature=0)
        resp = await llm.ainvoke([SystemMessage(content=TOOL_SYSTEM), HumanMessage(content=prompt)])
        raw = resp.content.strip().strip("```json").strip("```").strip()
        decision = json.loads(raw)
    except Exception as exc:
        logger.error("Tool loop LLM failed", extra={"error": str(exc)})
        return _final_answer_state(
            "Sorry, I ran into an issue processing your request. Please try again.", tool_ctx
        )

    action = decision.get("action", "final_answer")

    if action == "final_answer":
        response_text = decision.get("response") or "How can I help with your shopping?"
        # LLM decides which products to show (if any)
        product_indices = decision.get("product_indices") or []
        selected_products = [current_products[i] for i in product_indices if 0 <= i < len(current_products)]
        logger.info("Node: tool_loop — final answer", extra={"request_id": state.get("request_id"), "product_count": len(selected_products)})
        return _final_answer_state(response_text, tool_ctx, selected_products)

    # ── Execute tool ─────────────────────────────────────────────────────────
    tool_name = decision.get("tool")
    tool_input = decision.get("tool_input") or {}
    tool_result: dict[str, Any] = {}

    logger.info("Node: tool_loop — calling tool", extra={
        "tool": tool_name, "input": tool_input, "request_id": state.get("request_id")
    })

    if tool_name == TOOL_PRODUCT_DETAIL:
        pid = tool_input.get("product_id", "")
        tool_result = await product_detail_tool(pid)
        status = tool_result.get("status", "NOT_FOUND")
        tool_ctx["last_tool_used"] = TOOL_PRODUCT_DETAIL
        tool_ctx["last_tool_status"] = status
        tool_ctx["last_product_id"] = pid

        # Issue #1: if not found in cache, escalate to search_tool automatically
        if status == "NOT_FOUND":
            logger.info("product_detail NOT_FOUND — falling back to search_tool", extra={"product_id": pid})
            query = _build_fallback_query(pid, current_products)
            tool_result = await search_tool(query, state.get("structured_query"))
            tool_ctx["last_tool_used"] = TOOL_SEARCH
            tool_ctx["last_tool_status"] = tool_result.get("status", "error")
            tool_name = TOOL_SEARCH  # update for formatting

    elif tool_name == TOOL_SEARCH:
        query = tool_input.get("query", "")
        # Allow structured overrides passed by LLM (e.g. updated price range)
        update_params = tool_input.get("update_params") or {}
        sq = dict(state.get("structured_query") or {})
        if update_params:
            sq.update(update_params)
        tool_result = await search_tool(query, sq)
        tool_ctx["last_tool_used"] = TOOL_SEARCH
        tool_ctx["last_tool_status"] = tool_result.get("status", "error")

    else:
        logger.warning("Unknown tool", extra={"tool": tool_name})
        tool_result = {"status": "error", "message": f"Unknown tool: {tool_name}"}

    # Human-readable summary for the message log
    tool_result_msg = _format_tool_result(tool_name, tool_result)

    # Extract products from tool result if available
    tool_products = _extract_products_from_result(tool_name, tool_result)

    tool_ctx["iteration"] = iteration + 1
    tool_ctx["action"] = "call_tool"

    messages_update = [{"role": "tool", "content": tool_result_msg, "products": tool_products}]

    logger.info("Node: tool_loop — tool executed", extra={
        "tool": tool_name, "status": tool_ctx.get("last_tool_status"),
        "request_id": state.get("request_id")
    })

    return {
        "tool_context": tool_ctx,
        "messages": messages_update,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_recent_products(messages: list) -> list[dict]:
    """Pull product list from the most recent assistant message that has products."""
    for msg in reversed(messages):
        products = msg.get("products") if isinstance(msg, dict) else []
        if products:
            return products
    return []


def _build_fallback_query(product_id: str, current_products: list[dict]) -> str:
    """Build a search query from a product_id that wasn't found in cache."""
    for p in current_products:
        if p.get("product_id") == product_id:
            return p.get("title", product_id)
    return product_id


def _format_tool_result(tool_name: str, result: dict) -> str:
    """Format tool result as a human-readable message for the conversation log."""
    if tool_name == TOOL_PRODUCT_DETAIL:
        if result.get("status") == "found":
            product = result.get("product", {})
            title = product.get("title", "Unknown")
            price = product.get("price") or {}
            price_str = f"{price.get('currency', 'USD')} {price.get('value', 0)}"
            rating = product.get("rating", 0)
            return (
                f"Product Details found:\n"
                f"Title: {title}\n"
                f"Price: {price_str}\n"
                f"Rating: {rating}/5\n"
                f"URL: {product.get('url', 'N/A')}"
            )
        return "The requested product details could not be found in cache — fell back to search."

    if tool_name == TOOL_SEARCH:
        if result.get("status") == "success":
            results = result.get("results", [])
            if results:
                summary = f"Search found {len(results)} products:\n"
                for i, p in enumerate(results[:5], 1):
                    price = p.get("price") or {}
                    summary += (
                        f"{i}. {p.get('title', 'Unknown')} — "
                        f"{price.get('currency', 'USD')} {price.get('value', 0)}\n"
                    )
                return summary
            return "Search returned no matching products."
        return f"Search failed: {result.get('error', 'Unknown error')}"

    return f"Tool result: {json.dumps(result)[:300]}"


def _extract_products_from_result(tool_name: str, result: dict) -> list[dict]:
    """Extract product list from tool result for display."""
    if tool_name == TOOL_PRODUCT_DETAIL:
        if result.get("status") == "found":
            product = result.get("product", {})
            return [product] if product else []
    elif tool_name == TOOL_SEARCH:
        if result.get("status") == "success":
            return result.get("results", [])
    return []


def _final_answer_state(text: str, tool_ctx: dict, products: list[dict] | None = None) -> dict:
    return {
        "tool_context": {**tool_ctx, "iteration": MAX_TOOL_ITERATIONS, "action": "final_answer"},
        "messages": [{"role": "assistant", "content": text, "products": products or []}],
        "final_products": products or [],
    }


def should_continue_tool_loop(state: AgentState) -> str:
    """Conditional edge: loop back or finish."""
    tool_ctx = state.get("tool_context") or {}
    iteration = int(tool_ctx.get("iteration") or 0)
    action = tool_ctx.get("action", "")

    if action == "final_answer":
        logger.info("Tool loop stopping: final answer given")
        return "done"

    if iteration >= MAX_TOOL_ITERATIONS:
        logger.info("Tool loop stopping: max iterations reached", extra={"iteration": iteration})
        return "done"

    return "loop"
