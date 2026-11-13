"""إشعارات المتابعة المستحقة للمندوبين — تُولَّد مرة يومياً لكل قائد مستحق."""
from datetime import datetime, timedelta, timezone

from . import models
from .accounting import local_today
from .exports import LOCAL_TZ
from .push import notify_rep

KIND = "crm_followup"


def ensure_followup_notifications(db, rep) -> int:
    """للقيادة المسندة للمندوب: متابعة مستحقة اليوم أو متأخرة + ليست فائزة/مفقودة
    → تنبيه في صندوقه + Push (dedup: تنبيه واحد لكل قائد في اليوم المحلي)."""
    from datetime import datetime as _dt, time as _time, timezone as _tz
    company_id = rep.company_id
    today = local_today()
    day_start_local = _dt.combine(today, _time.min, tzinfo=LOCAL_TZ)
    today_start_u = day_start_local.astimezone(_tz.utc).replace(tzinfo=None)

    leads = db.query(models.CrmLead).filter(
        models.CrmLead.company_id == company_id,
        models.CrmLead.assigned_rep_id == rep.id,
        models.CrmLead.status.notin_(("won", "lost")),
        models.CrmLead.next_follow_up_at.isnot(None),
        models.CrmLead.next_follow_up_at < _dt.combine(today + timedelta(days=1), _time.min, tzinfo=LOCAL_TZ).astimezone(_tz.utc).replace(tzinfo=None),
    ).all()
    if not leads:
        return 0

    day_key = today.isoformat()
    existing_refs = {
        (n.ref_id, day_key)
        for n in db.query(models.RepNotification).filter(
            models.RepNotification.rep_id == rep.id,
            models.RepNotification.kind == KIND,
            models.RepNotification.created_at >= today_start_u,
        ).all()
    }
    created = 0

    def _naive_utc(dt: datetime) -> datetime:
        # Postgres يعيد timestamptz aware، وSQLite يعيد naive — وحّد إلى naive-UTC (اتفاقية النظام)
        if dt is None:
            return None
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    for lead in leads:
        if (lead.id, day_key) in existing_refs:
            continue
        fu = _naive_utc(lead.next_follow_up_at)
        overdue = fu and fu < today_start_u
        title = ("متابعة متأخرة: " if overdue else "متابعة اليوم: ") + lead.name
        body = f"{lead.code} · {lead.phone or 'بلا هاتف'} — {('متأخرة عن موعدها!' if overdue else 'مواعدها اليوم')}"
        notify_rep(db, rep.id, kind=KIND, title=title, body=body, ref_id=lead.id)
        created += 1
    return created
