"""تشفير أسرار ETA المخزنة نصًا صريحًا — سكربت لمرة واحدة، آمن للتكرار (idempotent).

الاستخدام (بعد ضبط ETA_ENC_KEY في بيئة التشغيل):
    docker exec -e ETA_ENC_KEY=<المفتاح> ai-erp-system-1-backend-1 \
        python /srv/scripts/encrypt_eta_secrets.py

بدون ETA_ENC_KEY: يخرج بلا عمل (الأسرار تبقى نصًا صريحًا كما هي).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models as m  # noqa: E402
from app.eta import eta_secret_encrypt  # noqa: E402


def main() -> int:
    key = os.getenv("ETA_ENC_KEY", "")
    if not key:
        print("ETA_ENC_KEY غير مضبوط — لا شيء سيُشفَّر. اضبط المفتاح أولًا.")
        return 1

    engine = create_engine(os.environ["DATABASE_URL"])
    db = Session(engine)
    changed = 0

    for company in db.execute(select(m.Company)).scalars():
        for field in ("eta_client_secret", "eta_private_key"):
            value = getattr(company, field)
            if value and not value.startswith("enc:v1:"):
                setattr(company, field, eta_secret_encrypt(value))
                changed += 1

    for device in db.execute(select(m.EtaDevice)).scalars():
        if device.private_key and not device.private_key.startswith("enc:v1:"):
            device.private_key = eta_secret_encrypt(device.private_key)
            changed += 1

    db.commit()
    print(f"تم تشفير {changed} قيمة سرية — المحفوظة مشفرة أصلًا لم تُمس.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
