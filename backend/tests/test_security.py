from app.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)


def test_password_hashes_are_salted_and_verify_correct_passwords():
    first_hash = hash_password("correct horse battery staple")
    second_hash = hash_password("correct horse battery staple")

    assert first_hash != second_hash
    assert verify_password("correct horse battery staple", first_hash)
    assert verify_password("correct horse battery staple", second_hash)
    assert not verify_password("wrong password", first_hash)


def test_password_verification_rejects_malformed_hashes():
    assert not verify_password("password", "")
    assert not verify_password("password", "unknown$1$c2FsdA==$ZGlnZXN0")
    assert not verify_password("password", "pbkdf2_sha256$bad$c2FsdA==$ZGlnZXN0")


def test_access_token_round_trip_and_rejects_invalid_tokens():
    token = create_access_token(123)

    assert decode_access_token(token) == {'id': 123, 'ver': 1}
    assert decode_access_token("not-a-token") is None


def test_access_token_rejects_expired_tokens():
    token = create_access_token(123, expires_minutes=-1)

    assert decode_access_token(token) is None


def test_access_token_expiration_default_is_60_minutes():
    """Default JWT expiration must be 60 minutes (not 480) for security."""
    assert ACCESS_TOKEN_EXPIRE_MINUTES == 60


def test_access_token_expires_after_configured_minutes(monkeypatch):
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    import importlib
    import app.security
    importlib.reload(app.security)
    from app.security import create_access_token, decode_access_token

    token = app.security.create_access_token(1)
    # Valid immediately
    assert app.security.decode_access_token(token) == {'id': 1, 'ver': 1}
    # Force-expired
    expired = app.security.create_access_token(1, expires_minutes=-1)
    assert app.security.decode_access_token(expired) is None
    importlib.reload(app.security)


def test_access_token_rejects_tampered_signature():
    import jwt

    tampered = jwt.encode({"sub": "99", "exp": 9999999999}, "wrong-secret", algorithm="HS256")
    assert decode_access_token(tampered) is None


def test_create_access_token_with_custom_expiry():
    token = create_access_token(123, expires_minutes=15)
    payload = decode_access_token(token)
    assert payload == {"id": 123, "ver": 1}


def test_hash_password_rejects_empty_password():
    h = hash_password("")
    assert h.startswith("pbkdf2_sha256$")
    assert verify_password("", h)
    assert not verify_password("non-empty", h)
