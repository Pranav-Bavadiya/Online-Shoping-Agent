"""Thread cart REST API — direct cart management outside agent."""
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.db import collections as col
from app.models.product_cache import RawProduct
from app.schemas.cart import (
    AddToCartRequest, CartResponse, RemoveFromCartRequest, UpdateCartItemRequest,
)
from app.services import cart_service, seller_service

router = APIRouter(prefix="/threads/{thread_id}/cart", tags=["cart"])


async def _verify_thread(thread_id: str, user_id: str):
    thread = await col.threads().find_one({"_id": thread_id, "user_id": user_id})
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")


async def _resolve_product(product_id: str) -> dict:
    """Look up a product from cache or local products."""
    # Try local product
    if product_id.startswith("local_"):
        doc_id = product_id[len("local_"):]
        doc = await col.local_products().find_one({"_id": doc_id, "is_active": True})
        if doc:
            return {
                "product_id": product_id,
                "title": doc.get("title", ""),
                "price": {"value": float(doc.get("price", 0)), "currency": doc.get("currency", "INR")},
                "image": doc.get("image", ""),
                "url": "",
                "source": "local",
                "can_buy_here": True,
                "redirect_url": "",
            }
    # Try product_lookup_map
    lookup = await col.product_lookup_map().find_one({"product_id": product_id})
    if lookup:
        from bson import ObjectId
        doc = await col.product_cache().find_one({"_id": ObjectId(lookup["cache_doc_id"])})
        if doc:
            for p in doc.get("raw_results", []):
                if p.get("product_id") == product_id:
                    return {
                        **p,
                        "can_buy_here": p.get("source") == "local",
                        "redirect_url": p.get("url", ""),
                    }
    raise HTTPException(status_code=404, detail="Product not found")


@router.get("", response_model=CartResponse)
async def get_cart(thread_id: str, user=Depends(get_current_user)):
    await _verify_thread(thread_id, user["_id"])
    cart = await cart_service.get_cart(thread_id, user["_id"])
    summary = cart_service.build_cart_summary(cart)
    return CartResponse(
        thread_id=thread_id,
        items=summary["items"],
        purchasable_count=summary["purchasable_count"],
        external_count=summary["external_count"],
        estimated_total=summary["estimated_total"],
    )


@router.post("/add", status_code=201)
async def add_to_cart(thread_id: str, body: AddToCartRequest, user=Depends(get_current_user)):
    await _verify_thread(thread_id, user["_id"])
    product = await _resolve_product(body.product_id)
    cart = await cart_service.add_item(thread_id, user["_id"], product, body.quantity)
    summary = cart_service.build_cart_summary(cart)
    return {"message": "Added to cart", "cart": summary}


@router.post("/remove")
async def remove_from_cart(thread_id: str, body: RemoveFromCartRequest, user=Depends(get_current_user)):
    await _verify_thread(thread_id, user["_id"])
    cart = await cart_service.remove_item(thread_id, body.cart_item_id)
    return {"message": "Item removed", "cart": cart_service.build_cart_summary(cart)}


@router.put("/update")
async def update_cart_item(thread_id: str, body: UpdateCartItemRequest, user=Depends(get_current_user)):
    await _verify_thread(thread_id, user["_id"])
    cart = await cart_service.update_quantity(thread_id, body.cart_item_id, body.quantity)
    return {"cart": cart_service.build_cart_summary(cart)}


@router.delete("/clear", status_code=204)
async def clear_cart(thread_id: str, user=Depends(get_current_user)):
    await _verify_thread(thread_id, user["_id"])
    await cart_service.clear_cart(thread_id)
