"""Thread routes — list, get, rename, delete."""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user_id
from app.graph.checkpointer.memory import checkpointer
from app.schemas.thread import (
    MessageSchema, RenameTitleRequest,
    ThreadDetailResponse, ThreadSummaryResponse,
)
from app.services import thread_service

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
    user_id: str = Depends(get_current_user_id),
):
    # Verify ownership (raises 403/404 if invalid)
    await thread_service.verify_thread_ownership(thread_id, user_id)

    # Load messages from checkpointer
    raw_messages = await checkpointer.get_messages(thread_id)

    messages = []
    for m in raw_messages:
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

    return ThreadDetailResponse(thread_id=thread_id, messages=messages)


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
