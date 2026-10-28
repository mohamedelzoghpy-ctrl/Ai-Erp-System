from app.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
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

    assert decode_access_token(token) == 123
    assert decode_access_token("not-a-token") is None


def test_access_token_rejects_expired_tokens():
    token = create_access_token(123, expires_minutes=-1)

    assert decode_access_token(token) is None


def test_placeholder_secret_key_is_refused_at_startup():
    import subprocess
    import sys

    code = "import app.security"
    bad = subprocess.run([sys.executable, "-c", code], env={"SECRET_KEY": "change-me-to-a-long-random-string", "PATH": ""}, capture_output=True, text=True)
    assert bad.returncode != 0 and "placeholder" in bad.stderr
    good = subprocess.run([sys.executable, "-c", code], env={"SECRET_KEY": "x" * 48, "PATH": ""}, capture_output=True, text=True)
    assert good.returncode == 0, good.stderr
