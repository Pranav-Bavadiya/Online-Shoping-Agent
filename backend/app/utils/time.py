"""Time utilities."""
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utc_timestamp() -> float:
    return datetime.now(timezone.utc).timestamp()


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
