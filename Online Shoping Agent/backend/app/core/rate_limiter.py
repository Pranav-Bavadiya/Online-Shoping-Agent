"""SlowAPI rate limiting helpers."""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# One global limiter instance — keyed on client IP
limiter = Limiter(key_func=get_remote_address)

SEARCH_RATE = f"{settings.rate_limit_per_minute}/minute"
DEFAULT_RATE = "60/minute"
