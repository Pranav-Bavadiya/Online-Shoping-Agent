"""FastAPI dependencies — auth, db, rate limiting."""
from fastapi import Depends, Header
from jose import JWTError

from app.core.security import extract_user_id
from app.exceptions.auth import InvalidTokenError, UnauthorizedError


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
