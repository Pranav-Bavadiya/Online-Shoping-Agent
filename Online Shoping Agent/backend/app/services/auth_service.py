"""Auth service — signup, login, Google OAuth."""
from datetime import datetime
from typing import Optional

import requests
from google.auth.transport import requests as grequests
from google.oauth2 import id_token

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import create_access_token, hash_password, verify_password
from app.db import collections as col
from app.exceptions.auth import InvalidCredentialsError, InvalidTokenError
from app.exceptions.base import ConflictError
from app.utils.uuid import new_user_id

logger = get_logger(__name__)


async def signup(name: str, email: str, password: str, phone: Optional[str] = None) -> dict:
    """Create a new user account."""
    existing = await col.users().find_one({"email": email})
    if existing:
        raise ConflictError("Email already registered")

    user_id = new_user_id()
    now = datetime.utcnow()
    user_doc = {
        "_id": user_id,
        "name": name,
        "email": email,
        "password_hash": hash_password(password),
        "google_id": None,
        "phone": phone,
        "addresses": [],
        "default_address_id": None,
        "profile_completed": bool(phone),
        "created_at": now,
        "updated_at": now,
    }
    await col.users().insert_one(user_doc)
    token = create_access_token(subject=user_id)
    logger.info("User signed up", extra={"user_id": user_id})
    return {"access_token": token, "profile_completed": user_doc["profile_completed"]}


async def login(email: str, password: str) -> dict:
    """Authenticate with email + password."""
    user = await col.users().find_one({"email": email})
    if not user:
        raise InvalidCredentialsError()
    pw_hash = user.get("password_hash")
    if not pw_hash or not verify_password(password, pw_hash):
        raise InvalidCredentialsError()

    token = create_access_token(subject=user["_id"])
    logger.info("User logged in", extra={"user_id": user["_id"]})
    return {"access_token": token, "profile_completed": user.get("profile_completed", False)}


async def google_login(id_token_str: str) -> dict:
    """Verify Google ID token, create or link account."""
    try:
        idinfo = id_token.verify_oauth2_token(
            id_token_str,
            grequests.Request(),
            settings.google_client_id,
        )
    except Exception as exc:
        logger.warning("Google token verification failed", extra={"error": str(exc)})
        raise InvalidTokenError()

    google_id = idinfo.get("sub")
    email = idinfo.get("email", "")
    name = idinfo.get("name", email.split("@")[0])

    # 1. Check if google_id already registered
    user = await col.users().find_one({"google_id": google_id})

    # 2. Check by email
    if not user:
        user = await col.users().find_one({"email": email})
        if user:
            # Link Google ID to existing account
            await col.users().update_one(
                {"_id": user["_id"]},
                {"$set": {"google_id": google_id, "updated_at": datetime.utcnow()}}
            )
            user["google_id"] = google_id

    # 3. Create new user
    if not user:
        user_id = new_user_id()
        now = datetime.utcnow()
        user = {
            "_id": user_id,
            "name": name,
            "email": email,
            "password_hash": None,
            "google_id": google_id,
            "phone": None,
            "addresses": [],
            "default_address_id": None,
            "profile_completed": False,
            "created_at": now,
            "updated_at": now,
        }
        await col.users().insert_one(user)
        logger.info("New user via Google", extra={"user_id": user_id})

    token = create_access_token(subject=user["_id"])
    return {
        "access_token": token,
        "profile_completed": user.get("profile_completed", False),
    }
