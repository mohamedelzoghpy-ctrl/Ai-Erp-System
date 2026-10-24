"""Read-only audit trail for managers and admins."""

from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import require_manager
from ..exports import LOCAL_TZ
from ..pagination import paginate

router = APIRouter(prefix="/audit-logs", tags=["audit"])


def _day_start_utc(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=LOCAL_TZ).astimezone(timezone.utc)


@router.get("", response_model=List[schemas.AuditLogOut])
def list_audit_logs(
    response: Response,
    entity: Optional[str] = None,
    action: Optional[str] = None,
    username: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    q = db.query(models.AuditLog)
    if entity:
        q = q.filter(models.AuditLog.entity == entity)
    if action:
        q = q.filter(models.AuditLog.action == action)
    if username:
        q = q.filter(models.AuditLog.username == username.strip().lower())
    if date_from:
        q = q.filter(models.AuditLog.created_at >= _day_start_utc(date_from))
    if date_to:
        q = q.filter(models.AuditLog.created_at < _day_start_utc(date_to + timedelta(days=1)))
    return paginate(q, response, skip, limit, models.AuditLog.id.desc())
