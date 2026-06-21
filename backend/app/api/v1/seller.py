"""Seller API — registration, product management, order management."""
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.schemas.seller import (
    LocalProductCreateRequest, LocalProductResponse, LocalProductUpdateRequest,
    SellerDashboardSummary, SellerOrderResponse, SellerProfileResponse,
    SellerProfileUpdateRequest, SellerRegisterRequest,
)
from app.services import seller_service, order_service

router = APIRouter(prefix="/seller", tags=["seller"])


@router.post("/register", response_model=SellerProfileResponse)
async def register_seller(body: SellerRegisterRequest, user=Depends(get_current_user)):
    try:
        doc = await seller_service.register_seller(user["_id"], body.shop_name, body.description)
        return SellerProfileResponse(
            seller_id=doc["_id"], shop_name=doc["shop_name"],
            description=doc["description"], is_active=doc["is_active"]
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/profile", response_model=SellerProfileResponse)
async def get_seller_profile(user=Depends(get_current_user)):
    doc = await seller_service.get_seller_by_user(user["_id"])
    if not doc:
        raise HTTPException(status_code=404, detail="Seller profile not found")
    return SellerProfileResponse(
        seller_id=doc["_id"], shop_name=doc["shop_name"],
        description=doc["description"], is_active=doc["is_active"]
    )


@router.put("/profile", response_model=SellerProfileResponse)
async def update_seller_profile(body: SellerProfileUpdateRequest, user=Depends(get_current_user)):
    try:
        doc = await seller_service.update_seller_profile(user["_id"], body.model_dump())
        return SellerProfileResponse(
            seller_id=doc["_id"], shop_name=doc["shop_name"],
            description=doc["description"], is_active=doc["is_active"]
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


def _require_seller(user):
    if user.get("role") != "seller" or not user.get("seller_id"):
        raise HTTPException(status_code=403, detail="Seller account required")
    return user["seller_id"]


@router.get("/dashboard", response_model=SellerDashboardSummary)
async def seller_dashboard(user=Depends(get_current_user)):
    seller_id = _require_seller(user)
    products = await seller_service.get_seller_products(seller_id)
    active_orders = await order_service.get_seller_orders(seller_id, active_only=True)
    return SellerDashboardSummary(
        total_products=len(products),
        active_products=sum(1 for p in products if p.get("is_active")),
        active_orders=len(active_orders),
        pending_dispatches=sum(1 for o in active_orders if o.get("status") == "PAID"),
    )


@router.get("/products", response_model=list[LocalProductResponse])
async def list_products(user=Depends(get_current_user)):
    seller_id = _require_seller(user)
    docs = await seller_service.get_seller_products(seller_id)
    return [LocalProductResponse(**d) for d in docs]


@router.post("/products", response_model=LocalProductResponse, status_code=201)
async def create_product(body: LocalProductCreateRequest, user=Depends(get_current_user)):
    seller_id = _require_seller(user)
    doc = await seller_service.create_product(seller_id, body.model_dump())
    return LocalProductResponse(**doc)


@router.put("/products/{product_doc_id}", response_model=LocalProductResponse)
async def update_product(product_doc_id: str, body: LocalProductUpdateRequest, user=Depends(get_current_user)):
    seller_id = _require_seller(user)
    try:
        doc = await seller_service.update_product(product_doc_id, seller_id, body.model_dump(exclude_none=True))
        return LocalProductResponse(**doc)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/products/{product_doc_id}", status_code=204)
async def delete_product(product_doc_id: str, user=Depends(get_current_user)):
    seller_id = _require_seller(user)
    try:
        await seller_service.delete_product(product_doc_id, seller_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/orders")
async def list_seller_orders(user=Depends(get_current_user)):
    seller_id = _require_seller(user)
    docs = await order_service.get_seller_orders(seller_id, active_only=True)
    return {"orders": [_fmt_order(d) for d in docs]}


@router.get("/orders/history")
async def seller_order_history(user=Depends(get_current_user)):
    seller_id = _require_seller(user)
    docs = await order_service.get_seller_orders(seller_id, active_only=False)
    return {"orders": [_fmt_order(d) for d in docs]}


@router.post("/orders/{order_id}/dispatch")
async def dispatch_order(order_id: str, user=Depends(get_current_user)):
    seller_id = _require_seller(user)
    try:
        doc = await order_service.dispatch_order(order_id, seller_id)
        return {"message": "Order dispatched", "order": _fmt_order(doc)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _fmt_order(d: dict) -> dict:
    return {
        "order_id": d.get("_id", ""),
        "user_id": d.get("user_id", ""),
        "status": d.get("status", ""),
        "items": d.get("items", []),
        "total": d.get("total", 0),
        "currency": d.get("currency", "INR"),
        "delivery_address": d.get("delivery_address", {}),
        "created_at": str(d.get("created_at", "")),
    }
