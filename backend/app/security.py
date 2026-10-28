"""Password hashing (stdlib PBKDF2) and JWT helpers.

Configuration via environment variables:
  SECRET_KEY                   signing key for tokens. If unset, a random key is generated at
                               startup (tokens stop working after a restart) - set it in production.
  ACCESS_TOKEN_EXPIRE_MINUTES  token lifetime, default 480 (8 hours).
"""

import base64
import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

logger = logging.getLogger("erp.security")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_urlsafe(48)
    logger.warning("SECRET_KEY is not set: using a random key; all tokens are invalidated on restart.")
elif SECRET_KEY.startswith("change-me"):
    # The placeholder from .env.example is public: anyone could forge tokens with it.
    raise RuntimeError("SECRET_KEY still has the placeholder value from .env.example; set a long random string.")
elif len(SECRET_KEY) < 32:
    logger.warning("SECRET_KEY is shorter than 32 characters; use a longer random key.")

_PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_b64, digest_b64 = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(salt_b64), int(iterations)
        )
        return hmac.compare_digest(digest, base64.b64decode(digest_b64))
    except (ValueError, TypeError):
        return False


# Used to keep login timing similar whether or not the username exists.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def create_access_token(user_id: int, expires_minutes: Optional[int] = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes or ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": str(user_id), "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[int]:
    """Returns the user id, or None if the token is invalid or expired."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
