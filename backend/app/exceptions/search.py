"""Search-specific exceptions."""
from app.exceptions.base import AppException


class SearchProviderError(AppException):
    def __init__(self, detail: str = "Search provider error"):
        super().__init__(status_code=502, detail=detail)


class SearchTimeoutError(AppException):
    def __init__(self):
        super().__init__(status_code=504, detail="Search provider timed out")
