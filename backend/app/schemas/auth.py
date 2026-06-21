"""Auth request/response schemas."""
from typing import Optional
from pydantic import BaseModel, EmailStr


class SignupRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    phone: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleLoginRequest(BaseModel):
    id_token: str


class CreatePasswordRequest(BaseModel):
    """Used by Google-authenticated users to add a password to their account."""
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    profile_completed: bool = True
    # Lets frontend know whether to show "Create Password" screen after Google login
    has_password: bool = False


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None


class AddressRequest(BaseModel):
    line1: str
    line2: str = ""
    city: str
    state: str
    pincode: str
    country: str = "India"


class AddressResponse(BaseModel):
    id: str
    line1: str
    line2: str
    city: str
    state: str
    pincode: str
    country: str


class UserResponse(BaseModel):
    user_id: str
    name: str
    email: str
    phone: Optional[str]
    profile_completed: bool
    addresses: list[AddressResponse] = []
    default_address_id: Optional[str] = None
    # True if password_hash exists on the user document
    has_password: bool = False
    # Lets frontend know seller status without a 404-probe on /seller/profile
    role: str = "customer"
    seller_id: Optional[str] = None


class CreatePasswordResponse(BaseModel):
    message: str
    has_password: bool = True
