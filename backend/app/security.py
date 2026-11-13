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
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

logger = logging.getLogger("erp.security")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_urlsafe(48)
    logger.warning("SECRET_KEY is not set: using a random key; all tokens are invalidated on restart.")
elif len(SECRET_KEY) < 32:
    logger.warning(
        "SECRET_KEY is shorter than the recommended 32 bytes (%d given) — rotate it with: "
        "python3 -c \"import secrets; print(secrets.token_urlsafe(48))\"",
        len(SECRET_KEY),
    )

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


# --- سياسة كلمات السر: تُفحص عند الإسناد فقط (إعداد/إنشاء/تعديل) — القديمة لا تتأثر ---
_COMMON_PASSWORDS = {
    "password", "password1", "password123", "12345678", "123456789", "1234567890",
    "qwerty123", "qwertyuiop", "11111111", "00000000", "12121212", "abc12345",
    "letmein1", "iloveyou1", "admin1234", "welcome1", "monkey123", "dragon123",
    "passw0rd", "p@ssw0rd", "aaaaaaa1",
}


def validate_password_strength(password: str) -> Optional[str]:
    """يعيد رسالة الخطأ إن كانت كلمة السر ضعيفة، أو None إن قبلتها السياسة:
    8-128 حرفًا، أحرف + أرقام معًا، ليست في قائمة الشائعة."""
    if len(password) < 8:
        return "كلمة السر يجب أن تكون 8 أحرف على الأقل"
    if len(password) > 128:
        return "كلمة السر أطول من الحد المسموح (128)"
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "كلمة السر يجب أن تجمع أحرفًا وأرقامًا"
    if password.strip().lower() in _COMMON_PASSWORDS:
        return "كلمة السر ضعيفة جدًا (شائعة) — اختر غيرها"
    return None


def create_access_token(user_id: int, expires_minutes: Optional[int] = None, token_version: int = 1) -> str:
    """توكن يحمل إصدار الجلسة (ver) — رفع الإصدار على المستخدم يبطل كل التوكنات السابقة."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes or ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": str(user_id), "exp": expire, "ver": token_version, "typ": "access"}, SECRET_KEY, algorithm=ALGORITHM)


REFRESH_TOKEN_DAYS = int(os.getenv("REFRESH_TOKEN_DAYS", "30"))


def create_refresh_token(user_id: int, token_version: int = 1, days: Optional[int] = None) -> str:
    """توكن تجديد طويل الأمد للموبايل — يُبطل برفع إصدار الجلسة (logout-all/تغيير كلمة السر)."""
    expire = datetime.now(timezone.utc) + timedelta(days=days or REFRESH_TOKEN_DAYS)
    return jwt.encode({"sub": str(user_id), "exp": expire, "ver": token_version, "typ": "refresh"}, SECRET_KEY, algorithm=ALGORITHM)


def _decode_typed(token: str, expected_type: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("typ", "access") != expected_type:
            return None
        return {"id": int(payload["sub"]), "ver": int(payload.get("ver", 1))}
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def decode_refresh_token(token: str) -> Optional[dict]:
    """Returns {id, ver} for a refresh token only — access tokens are rejected here."""
    return _decode_typed(token, "refresh")


def decode_access_token(token: str) -> Optional[dict]:
    """Returns {id, ver} or None if the token is invalid or expired. ver=1 للتوكنات القديمة."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {"id": int(payload["sub"]), "ver": int(payload.get("ver", 1))}
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
