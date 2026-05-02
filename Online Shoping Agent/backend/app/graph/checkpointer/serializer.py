"""State serializer/deserializer for MongoDB checkpointer."""
import json
from datetime import datetime
from typing import Any


def _default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def serialize_state(state: dict) -> str:
    return json.dumps(state, default=_default)


def deserialize_state(raw: str) -> dict:
    return json.loads(raw)
