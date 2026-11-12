"""إشعارات Push لتطبيق المندوبين (FCM).

الوضع التدريجي المتعمد: بدون ضبط FCM_SERVER_KEY تعمل صامتة (الصف يسجل في
صندوق المندوب ويقرأه التطبيق عند الفتح — Pull)، وبمجرد ضبط المفتاح من
Firebase Console تُدفع فورًا. لا تعطل أي مسار عند غياب الشبكة/المفتاح.
"""
import logging
import os
from typing import List

logger = logging.getLogger("erp.push")

FCM_SERVER_KEY = os.getenv("FCM_SERVER_KEY", "")
FCM_URL = "https://fcm.googleapis.com/fcm/send"


def push_to_tokens(tokens: List[str], title: str, body: str, data: dict | None = None) -> int:
    """إرسال Push لعدة أجهزة — يعيد عدد الناجح. صامت عند غياب المفتاح."""
    if not FCM_SERVER_KEY or not tokens:
        return 0
    import json as _json
    import urllib.request
    sent = 0
    payload = _json.dumps({
        "notification": {"title": title, "body": body},
        "data": data or {},
    }).encode()
    for token in tokens:
        req = urllib.request.Request(
            FCM_URL, data=payload, method="POST",
            headers={
                "Authorization": f"key={FCM_SERVER_KEY}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    sent += 1
        except Exception as exc:  # جهاز غير صالح/شبكة — لا يعطل المسار الأصلي
            logger.warning("FCM push failed for token …%s: %s", token[-8:], exc)
    return sent


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
