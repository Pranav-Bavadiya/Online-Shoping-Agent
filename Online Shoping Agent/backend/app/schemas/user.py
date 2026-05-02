"""User schemas (re-exports from auth for convenience)."""
from app.schemas.auth import UserResponse, UpdateProfileRequest, AddressRequest, AddressResponse

__all__ = ["UserResponse", "UpdateProfileRequest", "AddressRequest", "AddressResponse"]
