"""Database exceptions."""
from app.exceptions.base import AppException


class DatabaseError(AppException):
    def __init__(self, detail: str = "Database error"):
        super().__init__(status_code=500, detail=detail)


class DuplicateKeyError(AppException):
    def __init__(self, field: str = "field"):
        super().__init__(status_code=409, detail=f"{field} already exists")
