"""Auth routes — signup, login, Google OAuth, profile management."""
from typing import Optional
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user_id
from app.core.logging import get_logger
from app.exceptions.base import NotFoundError
from app.schemas.auth import (
    AddressRequest, AddressResponse,
    CreatePasswordRequest, CreatePasswordResponse,
    GoogleLoginRequest, LoginRequest, SignupRequest,
    TokenResponse, UpdateProfileRequest, UserResponse,
)
from app.services import auth_service, user_service

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(body: SignupRequest):
    result = await auth_service.signup(
        name=body.name,
        email=body.email,
        password=body.password,
        phone=body.phone,
    )
    return TokenResponse(
        access_token=result["access_token"],
        profile_completed=result["profile_completed"],
        has_password=result.get("has_password", True),
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    result = await auth_service.login(email=body.email, password=body.password)
    return TokenResponse(
        access_token=result["access_token"],
        profile_completed=result["profile_completed"],
        has_password=result.get("has_password", False),
    )


@router.post("/google", response_model=TokenResponse)
async def google_login(body: GoogleLoginRequest):
    result = await auth_service.google_login(id_token_str=body.id_token)
    return TokenResponse(
        access_token=result["access_token"],
        profile_completed=result["profile_completed"],
        has_password=result.get("has_password", False),
    )


@router.post("/create-password", response_model=CreatePasswordResponse)
async def create_password(
    body: CreatePasswordRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Add a password to the authenticated user's account.

    Intended for Google-authenticated users who want to also be able to
    log in with email + password. Returns 400 if a password is already set,
    or if the new password fails strength validation.
    """
    result = await auth_service.create_password(user_id=user_id, password=body.password)
    return CreatePasswordResponse(
        message=result["message"],
        has_password=result["has_password"],
    )


@router.get("/me", response_model=UserResponse)
async def get_me(user_id: str = Depends(get_current_user_id)):
    user = await user_service.get_user_by_id(user_id)
    if not user:
        raise NotFoundError("User not found")
    addresses = [
        AddressResponse(**a) for a in user.get("addresses", [])
    ]
    return UserResponse(
        user_id=user["_id"],
        name=user["name"],
        email=user["email"],
        phone=user.get("phone"),
        profile_completed=user.get("profile_completed", False),
        addresses=addresses,
        default_address_id=user.get("default_address_id"),
        has_password=bool(user.get("password_hash")),
        role=user.get("role", "customer"),
        seller_id=user.get("seller_id"),
    )


@router.put("/update", response_model=UserResponse)
async def update_profile(
    body: UpdateProfileRequest,
    user_id: str = Depends(get_current_user_id),
):
    user = await user_service.update_profile(
        user_id=user_id,
        name=body.name,
        phone=body.phone,
    )
    addresses = [AddressResponse(**a) for a in user.get("addresses", [])]
    return UserResponse(
        user_id=user["_id"],
        name=user["name"],
        email=user["email"],
        phone=user.get("phone"),
        profile_completed=user.get("profile_completed", False),
        addresses=addresses,
        default_address_id=user.get("default_address_id"),
        has_password=bool(user.get("password_hash")),
        role=user.get("role", "customer"),
        seller_id=user.get("seller_id"),
    )


@router.post("/address", response_model=AddressResponse, status_code=201)
async def add_address(
    body: AddressRequest,
    user_id: str = Depends(get_current_user_id),
):
    addr = await user_service.add_address(user_id, body.model_dump())
    return AddressResponse(**addr)


@router.put("/address/{address_id}", status_code=204)
async def update_address(
    address_id: str,
    body: AddressRequest,
    user_id: str = Depends(get_current_user_id),
):
    await user_service.update_address(user_id, address_id, body.model_dump())


@router.delete("/address/{address_id}", status_code=204)
async def delete_address(
    address_id: str,
    user_id: str = Depends(get_current_user_id),
):
    await user_service.delete_address(user_id, address_id)


@router.put("/address/{address_id}/default", status_code=204)
async def set_default_address(
    address_id: str,
    user_id: str = Depends(get_current_user_id),
):
    await user_service.set_default_address(user_id, address_id)
