"""إشعارات Push لتطبيق المندوبين (FCM).

الوضع التدريجي المتعمد: بدون ضبط بيانات Firebase تعمل صامتة (الصف يسجل في
صندوق المندوب ويقرأه التطبيق عند الفتح — Pull)، وبمجرد الضبط تُدفع فورًا.
لا تعطل أي مسار عند غياب الشبكة/المفتاح.

وضعا الإرسال (الأولوية للـv1):
- HTTP v1 (المُوصى به): FCM_SERVICE_ACCOUNT_JSON (نص JSON كامل) أو
  FCM_SERVICE_ACCOUNT_PATH (مسار ملف حساب الخدمة) — OAuth2 موقّع بـRS256.
- Legacy (قديم): FCM_SERVER_KEY من واجهة Cloud Messaging القديمة — للتوافق فقط.
"""
import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
from typing import List, Optional

import jwt

logger = logging.getLogger("erp.push")

FCM_SERVER_KEY = os.getenv("FCM_SERVER_KEY", "")
FCM_SERVICE_ACCOUNT_JSON = os.getenv("FCM_SERVICE_ACCOUNT_JSON", "")
FCM_SERVICE_ACCOUNT_PATH = os.getenv("FCM_SERVICE_ACCOUNT_PATH", "")

FCM_V1_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
_OAUTH_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

# كاش توكن OAuth2 v1 — خيط آمن، يُجدد قبل الانتهاء بدقيقة
_v1_lock = threading.Lock()
_v1_cache: dict = {"token": None, "expires_at": 0.0, "project_id": None}


def _service_account() -> Optional[dict]:
    """بيانات حساب الخدمة: من المتغير النصي أو مسار الملف."""
    raw = FCM_SERVICE_ACCOUNT_JSON
    if not raw and FCM_SERVICE_ACCOUNT_PATH:
        try:
            with open(FCM_SERVICE_ACCOUNT_PATH, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            logger.warning("FCM service account file unreadable: %s", exc)
            return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if data.get("client_email") and data.get("private_key"):
            return data
        logger.warning("FCM service account JSON missing client_email/private_key")
    except (ValueError, TypeError) as exc:
        logger.warning("FCM_SERVICE_ACCOUNT_JSON is not valid JSON: %s", exc)
    return None


def _v1_access_token(sa: dict) -> Optional[str]:
    """OAuth2 access token لحساب الخدمة — موقّع RS256 عبر PyJWT (بلا مكتبات إضافية)."""
    now = time.time()
    with _v1_lock:
        if _v1_cache["token"] and now < _v1_cache["expires_at"] - 60 and _v1_cache["project_id"] == sa.get("project_id"):
            return _v1_cache["token"]
        try:
            assertion = jwt.encode(
                {
                    "iss": sa["client_email"],
                    "scope": _OAUTH_SCOPE,
                    "aud": sa.get("token_uri", "https://oauth2.googleapis.com/token"),
                    "iat": int(now),
                    "exp": int(now) + 3600,
                },
                sa["private_key"],
                algorithm="RS256",
            )
            body = urllib.parse.urlencode({
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            }).encode()
            req = urllib.request.Request(
                sa.get("token_uri", "https://oauth2.googleapis.com/token"),
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            token = data.get("access_token")
            if not token:
                logger.warning("FCM v1 token exchange returned no access_token")
                return None
            _v1_cache.update({
                "token": token,
                "expires_at": now + int(data.get("expires_in", 3600)),
                "project_id": sa.get("project_id"),
            })
            return token
        except Exception as exc:
            logger.warning("FCM v1 token exchange failed: %s", exc)
            return None


def _push_v1(sa: dict, tokens: List[str], title: str, body: str, data: dict) -> int:
    access = _v1_access_token(sa)
    if not access:
        return 0
    project_id = sa.get("project_id", "")
    sent = 0
    for token in tokens:
        payload = json.dumps({
            "message": {
                "token": token,
                "notification": {"title": title, "body": body},
                "data": {k: str(v) for k, v in (data or {}).items()},
            }
        }).encode()
        req = urllib.request.Request(
            FCM_V1_URL.format(project_id=project_id),
            data=payload,
            method="POST",
            headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json; UTF-8"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 201):
                    sent += 1
        except Exception as exc:  # جهاز غير صالح/شبكة — لا يعطل المسار الأصلي
            logger.warning("FCM v1 push failed for token …%s: %s", token[-8:], exc)
    return sent


def _push_legacy(tokens: List[str], title: str, body: str, data: dict) -> int:
    sent = 0
    payload = json.dumps({
        "notification": {"title": title, "body": body},
        "data": data or {},
    }).encode()
    for token in tokens:
        req = urllib.request.Request(
            "https://fcm.googleapis.com/fcm/send",
            data=payload,
            method="POST",
            headers={"Authorization": f"key={FCM_SERVER_KEY}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    sent += 1
        except Exception as exc:  # جهاز غير صالح/شبكة — لا يعطل المسار الأصلي
            logger.warning("FCM legacy push failed for token …%s: %s", token[-8:], exc)
    return sent


def push_to_tokens(tokens: List[str], title: str, body: str, data: dict | None = None) -> int:
    """إرسال Push لعدة أجهزة — يعيد عدد الناجح. صامت عند غياب أي إعداد."""
    if not tokens:
        return 0
    sa = _service_account()
    if sa:
        return _push_v1(sa, tokens, title, body, data or {})
    if FCM_SERVER_KEY:
        return _push_legacy(tokens, title, body, data or {})
    return 0


def notify_rep(db, rep_id: int, *, kind: str, title: str, body: str, ref_id: int | None = None) -> bool:
    """تسجيل تنبيه في صندوق المندوب + دفعه لأجهزته المسجلة (إن ضُبط FCM)."""
    from . import models
    rep = db.query(models.SalesRep).get(rep_id)
    if rep is None:
        return False
    notif = models.RepNotification(
        company_id=rep.company_id, rep_id=rep_id, kind=kind,
        title=title, body=body, ref_id=ref_id,
    )
    db.add(notif)
    db.flush()
    tokens = [d.fcm_token for d in rep.devices]
    notif.pushed = push_to_tokens(tokens, title, body, {"kind": kind, "ref_id": str(ref_id or "")}) > 0
    db.commit()  # يُستدعى بعد commit المسار الأصلي — يحفظ الصندوق/الPush بنفسه
    return True
