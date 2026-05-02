"""Auth middleware helpers (not a blanket middleware — used via FastAPI deps)."""
# The actual auth enforcement is done in api/deps.py via FastAPI Depends.
# This module is kept as a lightweight re-export for clarity.
from app.api.deps import get_current_user_id

__all__ = ["get_current_user_id"]
