"""FastAPI dependencies — auth, db, rate limiting."""
from fastapi import Depends, Header
from jose import JWTError

from app.core.security import extract_user_id
from app.exceptions.auth import InvalidTokenError, UnauthorizedError
from app.exceptions.base import NotFoundError


async def get_current_user_id(authorization: str = Header(...)) -> str:
    """
    Extract and validate JWT from Authorization: Bearer <token> header.
    Returns user_id or raises HTTP 401.
    """
    if not authorization.startswith("Bearer "):
        raise UnauthorizedError("Authorization header must start with 'Bearer '")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        user_id = extract_user_id(token)
        return user_id
    except JWTError:
        raise InvalidTokenError()


async def get_current_user(user_id: str = Depends(get_current_user_id)) -> dict:
    """
    Resolve the full user document from the database for the authenticated request.
    Used by routes that need more than just the user_id (e.g. email, addresses,
    password_hash presence) — cart, checkout, search, orders, seller, auth routes.
    """
    from app.db import collections as col
    user = await col.users().find_one({"_id": user_id})
    if not user:
        raise NotFoundError("User not found")
    return user
