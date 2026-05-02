"""UUID generation helpers."""
import uuid


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_thread_id() -> str:
    return f"T_{uuid.uuid4().hex[:16]}"


def new_user_id() -> str:
    return f"U_{uuid.uuid4().hex[:16]}"


def new_request_id() -> str:
    return f"R_{uuid.uuid4().hex[:12]}"
