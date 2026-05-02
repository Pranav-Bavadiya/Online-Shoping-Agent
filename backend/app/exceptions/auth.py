"""Auth-specific exceptions."""
from fastapi import HTTPException


class UnauthorizedError(HTTPException):
    def __init__(self, detail: str = "Not authenticated"):
        super().__init__(
            status_code=401,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class InvalidTokenError(UnauthorizedError):
    def __init__(self):
        super().__init__(detail="Invalid or expired token")


class InvalidCredentialsError(UnauthorizedError):
    def __init__(self):
        super().__init__(detail="Invalid email or password")
