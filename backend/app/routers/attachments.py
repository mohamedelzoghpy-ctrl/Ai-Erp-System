"""المرفقات: صور الفواتير/الشيكات على السندات والقيود والأصول (تُخزن في قاعدة البيانات)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user, require_manager

router = APIRouter(prefix="/attachments", tags=["attachments"], dependencies=[Depends(get_current_user)])

MAX_SIZE = 5 * 1024 * 1024  # 5MB لكل مرفق
ALLOWED_TYPES = {"payment", "journal_entry", "fixed_asset"}
ALLOWED_MIME_PREFIXES = ("image/", "application/pdf")


def _verify_entity(db: Session, company_id: int, entity_type: str, entity_id: int) -> None:
    """التأكد أن الكيان الهدف موجود ضمن الشركة (لا مرفقات على كيانات وهمية/أجنبية)."""
    model = {"payment": models.Payment, "journal_entry": models.JournalEntry, "fixed_asset": models.FixedAsset}.get(entity_type)
    if model is None:
        raise HTTPException(422, f"نوع الكيان غير مدعوم: {entity_type}")
    obj = db.query(model).filter(model.id == entity_id, model.company_id == company_id).first()
    if obj is None:
        raise HTTPException(404, f"الكيان {entity_type} #{entity_id} غير موجود")


@router.get("/{attachment_id}/download")
def download_attachment(attachment_id: int, db: Session = Depends(get_db)):
    att = db.query(models.Attachment).filter(
        models.Attachment.id == attachment_id,
        models.Attachment.company_id == db.info["company_id"],
    ).first()
    if att is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    return Response(
        content=att.data,
        media_type=att.content_type,
        headers={"Content-Disposition": f'inline; filename="{att.filename}"', "Cache-Control": "no-store"},
    )


@router.get("/{entity_type}/{entity_id}", response_model=List[schemas.AttachmentOut])
def list_attachments(entity_type: str, entity_id: int, db: Session = Depends(get_db)):
    return db.query(models.Attachment).filter(
        models.Attachment.company_id == db.info["company_id"],
        models.Attachment.entity_type == entity_type,
        models.Attachment.entity_id == entity_id,
    ).order_by(models.Attachment.id).all()


@router.post("/{entity_type}/{entity_id}", response_model=schemas.AttachmentOut, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    entity_type: str,
    entity_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    company_id = db.info["company_id"]
    _verify_entity(db, company_id, entity_type, entity_id)
    content_type = file.content_type or "application/octet-stream"
    if not content_type.startswith(ALLOWED_MIME_PREFIXES):
        raise HTTPException(422, "المرفقات المسموحة: صور أو PDF فقط")
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(422, "الملف فارغ")
    if len(data) > MAX_SIZE:
        raise HTTPException(422, "أقصى حجم للمرفق 5 ميجابايت")
    att = models.Attachment(
        company_id=company_id,
        entity_type=entity_type,
        entity_id=entity_id,
        filename=(file.filename or "attachment")[:255],
        content_type=content_type,
        size=len(data),
        data=data,
        uploaded_by=user.id,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    audit(db, user, "create", "attachment", att.id, f"{entity_type} #{entity_id} ← {att.filename} ({att.size}B)")
    return att


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    att = db.query(models.Attachment).filter(
        models.Attachment.id == attachment_id,
        models.Attachment.company_id == db.info["company_id"],
    ).first()
    if att is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    audit(db, user, "delete", "attachment", att.id, f"{att.entity_type} #{att.entity_id} ← {att.filename}")
    db.delete(att)
    db.commit()
    return None
