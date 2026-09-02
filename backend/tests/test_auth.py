import jwt
import pytest

from app import auth


def test_hash_password_and_verify_roundtrip():
    hashed = auth.hash_password("password123")
    assert hashed != "password123"
    assert auth.verify_password("password123", hashed)


def test_verify_password_rejects_wrong_password():
    hashed = auth.hash_password("password123")
    assert not auth.verify_password("wrong-password", hashed)


def test_create_access_token_roundtrips_user_id():
    token = auth.create_access_token(42)
    payload = jwt.decode(token, auth._secret_key(), algorithms=[auth.ALGORITHM])
    assert payload["sub"] == "42"


def test_secret_key_missing_raises(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        auth._secret_key()
