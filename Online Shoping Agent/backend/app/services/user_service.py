"""User service — profile and address CRUD."""
from datetime import datetime
from typing import Optional

from app.core.logging import get_logger
from app.db import collections as col
from app.exceptions.base import NotFoundError
from app.models.user import Address, UserModel
from app.utils.uuid import new_uuid

logger = get_logger(__name__)


async def get_user_by_id(user_id: str) -> Optional[dict]:
    return await col.users().find_one({"_id": user_id})


async def get_user_by_email(email: str) -> Optional[dict]:
    return await col.users().find_one({"email": email})


async def update_profile(user_id: str, name: Optional[str], phone: Optional[str]) -> dict:
    update: dict = {"updated_at": datetime.utcnow()}
    if name:
        update["name"] = name
    if phone:
        update["phone"] = phone
        update["profile_completed"] = True
    result = await col.users().find_one_and_update(
        {"_id": user_id},
        {"$set": update},
        return_document=True,
    )
    if not result:
        raise NotFoundError("User not found")
    return result


async def add_address(user_id: str, address_data: dict) -> dict:
    addr_id = new_uuid()
    address = {**address_data, "id": addr_id}
    await col.users().update_one(
        {"_id": user_id},
        {
            "$push": {"addresses": address},
            "$set": {"updated_at": datetime.utcnow()},
        }
    )
    return address


async def update_address(user_id: str, address_id: str, address_data: dict) -> None:
    result = await col.users().update_one(
        {"_id": user_id, "addresses.id": address_id},
        {"$set": {
            "addresses.$": {**address_data, "id": address_id},
            "updated_at": datetime.utcnow(),
        }},
    )
    if result.matched_count == 0:
        raise NotFoundError("Address not found")


async def delete_address(user_id: str, address_id: str) -> None:
    await col.users().update_one(
        {"_id": user_id},
        {
            "$pull": {"addresses": {"id": address_id}},
            "$set": {"updated_at": datetime.utcnow()},
        }
    )


async def set_default_address(user_id: str, address_id: str) -> None:
    await col.users().update_one(
        {"_id": user_id},
        {"$set": {"default_address_id": address_id, "updated_at": datetime.utcnow()}}
    )
