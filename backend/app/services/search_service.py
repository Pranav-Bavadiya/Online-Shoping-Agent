"""Search service — orchestrates the LangGraph pipeline for a single query."""
from typing import Optional

from app.core.llm_factory import get_llm, is_llm_configured
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.core.logging import get_logger
from app.graph.builder import shopping_graph
from app.graph.checkpointer.memory import checkpointer
from app.services.cart_service import get_cart
from app.services.feedback_service import get_feedback_summary
from app.services.thread_service import create_thread, touch_thread, verify_thread_ownership
from app.utils.uuid import new_request_id

logger = get_logger(__name__)

TITLE_SYSTEM = "Generate a short (max 6 words) title for a shopping thread based on the user query. Return ONLY the title."


async def _generate_title(query: str) -> str:
    if not is_llm_configured():
        return " ".join(query.strip().split()[:5]).title() or "Shopping Session"
    try:
        llm = get_llm(temperature=0.4)
        resp = await llm.ainvoke([SystemMessage(content=TITLE_SYSTEM), HumanMessage(content=query)])
        return resp.content.strip().strip('"').strip("'")[:80]
    except Exception:
        return " ".join(query.strip().split()[:5]).title() or "Shopping Session"


async def handle_search(user_id: str, query: str, thread_id: Optional[str]) -> dict:
    request_id = new_request_id()
    logger.info("Search service start", extra={"user_id": user_id, "request_id": request_id})

    # ── Thread handling ───────────────────────────────────────────────────────
    if thread_id:
        await verify_thread_ownership(thread_id, user_id)
    else:
        title = await _generate_title(query)
        thread_id = await create_thread(user_id, title)
        logger.info("New thread created", extra={"thread_id": thread_id, "title": title})

    # ── Load saved state ──────────────────────────────────────────────────────
    saved_state = await checkpointer.load(thread_id) or {}
    existing_messages = saved_state.get("messages", [])
    conv_ctx = saved_state.get("conversation_context") or {}

    # Persist commerce state across turns
    selected_marketplaces = saved_state.get("selected_marketplaces") or ["local", "ebay"]
    checkout_state = saved_state.get("checkout") or {}

    # Load live cart from DB (source of truth)
    try:
        cart_doc = await get_cart(thread_id, user_id)
        thread_cart = {"items": cart_doc.get("items", [])}
    except Exception:
        thread_cart = saved_state.get("thread_cart") or {"items": []}

    all_messages = existing_messages + [{"role": "user", "content": query}]

    # ── Feedback summary ──────────────────────────────────────────────────────
    seen_pids = [
        p.get("product_id")
        for msg in existing_messages
        for p in (msg.get("products") if isinstance(msg, dict) else [])
        if p.get("product_id")
    ]
    feedback_summary = await get_feedback_summary(user_id, seen_pids) if seen_pids else {}

    try:
        from app.db import collections as col
        cursor = col.feedback().find(
            {"user_id": user_id, "action": {"$in": ["like", "click"]}}
        ).sort("timestamp", -1).limit(100)
        global_pids = [doc.get("product_id") async for doc in cursor]
        if global_pids:
            global_fb = await get_feedback_summary(user_id, global_pids)
            for pid, fb in global_fb.items():
                if pid not in feedback_summary:
                    feedback_summary[pid] = fb
    except Exception as exc:
        logger.warning("Failed to get global feedback", extra={"error": str(exc)})

    # ── Build initial state ───────────────────────────────────────────────────
    initial_state = {
        "messages": all_messages,
        "intent": None,
        "structured_query": saved_state.get("structured_query"),
        "retrieval": None,
        "raw_results": None,
        "filtered_results": None,
        "tool_context": {"iteration": 0},
        "conversation_context": conv_ctx,
        "clarification": {"pending": False, "question": None},
        "final_products": None,
        "user_feedback_summary": feedback_summary,
        # ── Commerce state ────────────────────────────────────────────────────
        "selected_marketplaces": selected_marketplaces,
        "thread_cart": thread_cart,
        "checkout": checkout_state,
        # ── Metadata ──────────────────────────────────────────────────────────
        "user_id": user_id,
        "thread_id": thread_id,
        "request_id": request_id,
    }

    # ── Execute graph ─────────────────────────────────────────────────────────
    try:
        final_state = await shopping_graph.ainvoke(initial_state)
    except Exception as exc:
        logger.error("Graph execution failed", extra={"error": str(exc), "request_id": request_id}, exc_info=True)
        final_state = {
            **initial_state,
            "messages": all_messages + [{
                "role": "assistant",
                "content": "Sorry, we weren't able to grant your request. Please try again.",
                "products": [],
            }],
            "final_products": [],
        }

    # ── Persist full state ────────────────────────────────────────────────────
    await checkpointer.save(thread_id, final_state)
    await touch_thread(thread_id)

    # ── Extract last assistant response ───────────────────────────────────────
    last_assistant = None
    for msg in reversed(final_state.get("messages", [])):
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "type", "")
        if role == "assistant":
            last_assistant = msg
            break

    if last_assistant is None:
        last_assistant = {"role": "assistant", "content": "How can I help?", "products": []}

    content = last_assistant.get("content", "") if isinstance(last_assistant, dict) else getattr(last_assistant, "content", "")
    products = last_assistant.get("products", []) if isinstance(last_assistant, dict) else []

    clr = final_state.get("clarification") or {}
    clarification_question = clr.get("question") if clr.get("pending") else None

    # ── Build commerce metadata for frontend ──────────────────────────────────
    updated_cart = final_state.get("thread_cart") or thread_cart
    updated_checkout = final_state.get("checkout") or {}
    updated_markets = final_state.get("selected_marketplaces") or selected_marketplaces

    logger.info("Search service done", extra={"thread_id": thread_id, "request_id": request_id})

    return {
        "thread_id": thread_id,
        "content": content or "",
        "products": products or [],
        "clarification_question": clarification_question,
        # ── Commerce state returned to frontend ───────────────────────────────
        "cart": updated_cart,
        "checkout": updated_checkout,
        "selected_marketplaces": updated_markets,
    }
