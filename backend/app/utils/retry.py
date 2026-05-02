"""Async retry decorator using tenacity."""
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from httpx import HTTPError

from app.core.constants import API_RETRY_ATTEMPTS
from app.core.logging import get_logger

logger = get_logger(__name__)


def api_retry(func):
    """Decorator: retry an async function up to API_RETRY_ATTEMPTS times on HTTP errors."""
    decorated = retry(
        stop=stop_after_attempt(API_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((HTTPError, TimeoutError, ConnectionError)),
        reraise=True,
    )(func)
    return decorated
