"""Audit trail helper: call before `db.commit()` so the entry is saved atomically with the change."""

from typing import Optional

from sqlalchemy.orm import Session

from . import models


def audit(db: Session, user: Optional[models.User], action: str, entity: str, target, summary: Optional[str] = None) -> None:
    """`target` is the record (its id is read after a flush, so new records work) or a plain id / None."""
    if target is not None and not isinstance(target, int):
        db.flush()
        target = target.id
    db.add(
        models.AuditLog(
            user_id=user.id if user else None,  # type: ignore
            username=user.username if user else None,  # type: ignore
            action=action,  # type: ignore
            entity=entity,  # type: ignore
            entity_id=target,  # type: ignore
            summary=summary,  # type: ignore
        )
    )
