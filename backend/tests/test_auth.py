"""Basic auth service tests (unit-level, no DB required)."""
import pytest
from app.core.security import hash_password, verify_password, create_access_token, extract_user_id


def test_password_hash_and_verify():
    pw = "SuperSecret123"
    hashed = hash_password(pw)
    assert hashed != pw
    assert verify_password(pw, hashed)
    assert not verify_password("wrong", hashed)


def test_jwt_round_trip():
    user_id = "U_test123"
    token = create_access_token(subject=user_id)
    extracted = extract_user_id(token)
    assert extracted == user_id
