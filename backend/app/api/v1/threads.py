"""Thread routes — list, get, rename, delete."""
from typing import Optional
from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user_id
from app.core.constants import (
    CHECKOUT_STEP_PAYMENT, CHECKOUT_STEP_PAYMENT_REQUIRED, ORDER_PAID,
)
from app.core.logging import get_logger
from app.db import collections as col
from app.graph.checkpointer.memory import checkpointer
from app.schemas.search import CheckoutStateSchema
from app.schemas.thread import (
    MessageSchema, RenameTitleRequest,
    ThreadDetailResponse, ThreadSummaryResponse,
)
from app.services import payment_service, thread_service
from app.services.checkout_finalize_service import finalize_payment_for_order

logger = get_logger(__name__)

router = APIRouter(prefix="/threads", tags=["threads"])


@router.get("", response_model=list[ThreadSummaryResponse])
async def list_threads(user_id: str = Depends(get_current_user_id)):
    threads = await thread_service.list_threads(user_id)
    return [
        ThreadSummaryResponse(
            thread_id=t["thread_id"],
            title=t["title"],
            updated_at=t["updated_at"],
        )
        for t in threads
    ]


@router.get("/{thread_id}", response_model=ThreadDetailResponse)
async def get_thread(
    thread_id: str,
    limit: int = Query(30, ge=1, le=200, description="Most-recent N messages to return"),
    before: Optional[str] = Query(None, description="Cursor from a previous response's next_cursor — load messages before this point"),
    user_id: str = Depends(get_current_user_id),
):
    # Verify ownership (raises 403/404 if invalid)
    await thread_service.verify_thread_ownership(thread_id, user_id)

    # Load messages from checkpointer — already in chronological order
    raw_messages = await checkpointer.get_messages(thread_id)

    # Paginate from the tail: `before` is the index to page backwards from
    # (defaults to the very end, i.e. most recent messages first load).
    total = len(raw_messages)
    try:
        end = total if before is None else max(0, min(total, int(before)))
    except ValueError:
        end = total
    start = max(0, end - limit)
    page = raw_messages[start:end]
    has_more = start > 0
    next_cursor = str(start) if has_more else None

    messages = []
    for m in page:
        role = m.get("role") if isinstance(m, dict) else getattr(m, "type", "user")
        content = m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
        products = m.get("products", []) if isinstance(m, dict) else []
        external_items = m.get("external_items", []) if isinstance(m, dict) else []
        has_external = m.get("has_external", False) if isinstance(m, dict) else False
        messages.append(MessageSchema(
            role=role,
            content=content,
            products=products,
            external_items=external_items,
            has_external=has_external,
        ))

    return ThreadDetailResponse(
        thread_id=thread_id, messages=messages,
        has_more=has_more, next_cursor=next_cursor,
    )


@router.get("/{thread_id}/checkout", response_model=CheckoutStateSchema)
async def get_thread_checkout(
    thread_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """
    Read the current checkout state for a thread without triggering a search/chat turn.

    Useful for refresh resilience: if a user reloads the page mid-payment, the
    frontend can call this to check whether checkout.step == "payment_required"
    or "payment_created" and show an informational "resume payment" banner —
    or "done" if the payment was already captured (e.g. via webhook) even
    though the frontend's own /checkout/confirm call never completed.

    RECONCILIATION: if the persisted checkout state looks unfinished
    (step is "payment_created" or "payment_required") but the associated
    order is already PAID in the database, this reconciles by running the
    same finalize_payment_for_order() the webhook uses, then returns the
    now-correct "done" state. This covers exactly the scenario where a
    webhook captured the payment but the browser crashed/refreshed before
    /checkout/confirm or /checkout/notify ever ran.

    NOTE: frontend should NOT auto-reopen the Razorpay widget on page load just
    because this returns a pending step — only use it to render a manual
    resume affordance (or a "Payment Completed" banner if step is "done"),
    to avoid surprising popups on mount.
    """
    await thread_service.verify_thread_ownership(thread_id, user_id)
    saved_state = await checkpointer.load(thread_id) or {}
    raw_checkout = dict(saved_state.get("checkout") or {})

    order_id = raw_checkout.get("current_order_id")
    unfinished_steps = {CHECKOUT_STEP_PAYMENT_REQUIRED, CHECKOUT_STEP_PAYMENT}
    if order_id and raw_checkout.get("step") in unfinished_steps:
        order = await col.orders().find_one({"_id": order_id})
        if order and order.get("status") == ORDER_PAID:
            logger.info("Reconciling stale checkout state against PAID order", extra={
                "thread_id": thread_id, "order_id": order_id,
            })
            payment = await payment_service.get_payment_by_order(order_id)
            razorpay_payment_id = (payment or {}).get("razorpay_payment_id", "")
            await finalize_payment_for_order(
                order_id=order_id, razorpay_payment_id=razorpay_payment_id, source="reconcile",
            )
            # Re-load the now-reconciled state
            saved_state = await checkpointer.load(thread_id) or {}
            raw_checkout = dict(saved_state.get("checkout") or {})

    return CheckoutStateSchema(
        active=raw_checkout.get("active", False),
        step=raw_checkout.get("step"),
        selected_cart_items=raw_checkout.get("selected_cart_items") or [],
        selected_address_id=raw_checkout.get("selected_address_id"),
        current_order_id=raw_checkout.get("current_order_id"),
        razorpay_order_id=raw_checkout.get("razorpay_order_id"),
        payment_status=raw_checkout.get("payment_status"),
        has_external=raw_checkout.get("has_external", False),
    )


@router.put("/{thread_id}", status_code=204)
async def rename_thread(
    thread_id: str,
    body: RenameTitleRequest,
    user_id: str = Depends(get_current_user_id),
):
    await thread_service.rename_thread(thread_id, user_id, body.title)


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: str,
    user_id: str = Depends(get_current_user_id),
):
    await thread_service.delete_thread(thread_id, user_id)
