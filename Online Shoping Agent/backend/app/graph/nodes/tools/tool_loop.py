"""Tool Loop Node — LLM-driven agent loop for chat intent (max 3 iterations)."""
import json
from typing import Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.core.constants import MAX_TOOL_ITERATIONS, TOOL_CONTEXT_MESSAGES, TOOL_PRODUCT_DETAIL, TOOL_SEARCH
from app.core.logging import get_logger
from app.graph.nodes.tools.product_tool import product_detail_tool
from app.graph.nodes.tools.search_tool import search_tool
from app.graph.state import AgentState

logger = get_logger(__name__)

TOOL_SYSTEM = """You are a helpful AI shopping assistant with access to tools.

Available tools:
1. product_detail: Get full details about a specific product.
   Input: {"tool": "product_detail", "product_id": "<id>"}

2. search_tool: Search for products.
   Input: {"tool": "search_tool", "query": "<search query>"}

Decision rules:
- If user asks about a specific product → use product_detail with the product_id
- If user wants to search for products → use search_tool
- If you can answer the question directly or based on previous context → use final_answer

ALWAYS respond with valid JSON:
{
  "action": "call_tool" | "final_answer",
  "tool": "<tool_name or null>",
  "tool_input": {<tool params or null>},
  "response": "<final answer if action is final_answer, else null>"
}"""


async def tool_loop_node(state: AgentState) -> dict:
    logger.info("Node: tool_loop start", extra={"request_id": state.get("request_id")})

    tool_ctx = dict(state.get("tool_context") or {})
    iteration = int(tool_ctx.get("iteration") or 0)
    tool_ctx["iteration"] = iteration  # Ensure iteration is set

    if iteration >= MAX_TOOL_ITERATIONS:
        # Force final answer
        logger.info("Node: tool_loop — max iterations reached", extra={"request_id": state.get("request_id")})
        final_response = "I've gathered the information you requested. Is there anything else you'd like to know?"
        return {
            "tool_context": {**tool_ctx, "iteration": iteration, "action": "final_answer"},
            "messages": [{"role": "assistant", "content": final_response, "products": []}],
            "final_products": [],
        }

    messages = state.get("messages", [])
    context_msgs = messages[-(TOOL_CONTEXT_MESSAGES):]
    context_str = "\n".join(
        f"{(m.get('role') if isinstance(m, dict) else getattr(m, 'type', 'unknown'))}: "
        f"{(m.get('content') if isinstance(m, dict) else getattr(m, 'content', ''))}"
        for m in context_msgs
    )

    conv_ctx = state.get("conversation_context") or {}
    tc_info = json.dumps(tool_ctx)

    prompt = f"""Conversation history:
{context_str}

Tool context: {tc_info}
Last product seen: {conv_ctx.get("last_product_id", "none")}
Last category: {conv_ctx.get("last_category", "none")}
Current iteration: {iteration + 1}/{MAX_TOOL_ITERATIONS}

Decide next action:"""

    if not settings.openai_api_key:
        # Fallback: just respond conversationally
        logger.warning("No OpenAI key — tool loop using fallback response")
        return _final_answer_state("I can help you find products. Please tell me what you're looking for!", tool_ctx)

    try:
        llm = ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key, temperature=0)
        resp = await llm.ainvoke([SystemMessage(content=TOOL_SYSTEM), HumanMessage(content=prompt)])
        raw = resp.content.strip().strip("```json").strip("```").strip()
        decision = json.loads(raw)
    except Exception as exc:
        logger.error("Tool loop LLM failed", extra={"error": str(exc)})
        return _final_answer_state("I encountered an issue. How can I assist you with your shopping?", tool_ctx)

    action = decision.get("action", "final_answer")

    if action == "final_answer":
        response_text = decision.get("response") or "How can I help with your shopping?"
        logger.info("Node: tool_loop — final answer", extra={"request_id": state.get("request_id")})
        return _final_answer_state(response_text, tool_ctx)

    # Call tool
    tool_name = decision.get("tool")
    tool_input = decision.get("tool_input") or {}
    tool_result: dict[str, Any] = {}

    logger.info("Node: tool_loop — calling tool", extra={
        "tool": tool_name, "input": tool_input, "request_id": state.get("request_id")
    })

    if tool_name == TOOL_PRODUCT_DETAIL:
        pid = tool_input.get("product_id", "")
        tool_result = await product_detail_tool(pid)
        tool_ctx["last_tool_used"] = TOOL_PRODUCT_DETAIL
        tool_ctx["last_tool_status"] = tool_result.get("status", "not_found")
        tool_ctx["last_product_id"] = pid

    elif tool_name == TOOL_SEARCH:
        query = tool_input.get("query", "")
        tool_result = await search_tool(query, state.get("structured_query"))
        tool_ctx["last_tool_used"] = TOOL_SEARCH
        tool_ctx["last_tool_status"] = tool_result.get("status", "error")

    else:
        logger.warning("Unknown tool", extra={"tool": tool_name})
        tool_result = {"status": "error", "message": f"Unknown tool: {tool_name}"}

    # Format tool result for LLM context in readable way
    tool_result_msg = _format_tool_result(tool_name, tool_result)

    tool_ctx["iteration"] = iteration + 1
    tool_ctx["action"] = "call_tool"  # Track that we called a tool

    # Append tool result message properly for next iteration
    # The tool result becomes context for the next LLM decision
    messages_update = [{"role": "user", "content": tool_result_msg, "products": []}]

    logger.info("Node: tool_loop — tool executed", extra={
        "tool": tool_name, "status": tool_ctx.get("last_tool_status"), "request_id": state.get("request_id")
    })

    return {
        "tool_context": tool_ctx,
        "messages": messages_update,  # This will be added via add_messages reducer
    }


def _format_tool_result(tool_name: str, result: dict) -> str:
    """Format tool result as human-readable message for LLM."""
    if tool_name == TOOL_PRODUCT_DETAIL:
        if result.get("status") == "found":
            product = result.get("product", {})
            title = product.get("title", "Unknown")
            price = product.get("price", {})
            price_str = f"{price.get('currency', 'USD')} {price.get('value', 0)}"
            rating = product.get("rating", 0)
            return (
                f"Product Details:\n"
                f"Title: {title}\n"
                f"Price: {price_str}\n"
                f"Rating: {rating}/5\n"
                f"URL: {product.get('url', 'N/A')}"
            )
        else:
            return "The requested product details could not be found."

    elif tool_name == TOOL_SEARCH:
        if result.get("status") == "success":
            results = result.get("results", [])
            if results:
                summary = f"Found {len(results)} products:\n"
                for i, p in enumerate(results[:5], 1):
                    summary += f"{i}. {p.get('title', 'Unknown')} - {p.get('price', {}).get('currency', 'USD')} {p.get('price', {}).get('value', 0)}\n"
                return summary
            else:
                return "No products found matching the search query."
        else:
            return f"Search failed: {result.get('error', 'Unknown error')}"

    else:
        return f"Tool result: {json.dumps(result)[:200]}"


def _final_answer_state(text: str, tool_ctx: dict) -> dict:
    return {
        "tool_context": {**tool_ctx, "iteration": MAX_TOOL_ITERATIONS},
        "messages": [{"role": "assistant", "content": text, "products": []}],
        "final_products": [],
    }


def should_continue_tool_loop(state: AgentState) -> str:
    """Conditional edge: loop back or finish."""
    tool_ctx = state.get("tool_context") or {}
    iteration = int(tool_ctx.get("iteration") or 0)
    action = tool_ctx.get("action", "")

    # Explicit check: if action was "final_answer", stop looping
    if action == "final_answer":
        logger.info("Tool loop stopping: final answer given")
        return "done"

    # Check iteration limit
    if iteration >= MAX_TOOL_ITERATIONS:
        logger.info("Tool loop stopping: max iterations reached", extra={"iteration": iteration})
        return "done"

    # Otherwise continue looping (tool was called, need to decide next)
    return "loop"
