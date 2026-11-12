"""المطابقة البنكية: استيراد كشف حساب البنك (CSV) ومطابقة سطوره مع سندات القبض والصرف.

CSV المتوقع (رؤوس إنجليزية أو عربية): date,tarikh / description,وصف / amount,مبلغ (موجب = داخِل، سالب = خارج) / reference اختياري.
المطابقة اليدوية تتحقق من تطابق المبلغ (±0.01) مع السند ومن أن السند على نفس البنك.
الملخص يقارن صافي الكشف المستورد مع رصيد حساب البنك في الدفاتر."""
import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user, require_manager

router = APIRouter(prefix="/banks/{bank_id}/statements", tags=["bank reconciliation"], dependencies=[Depends(get_current_user)])

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d")


def _bank_in_company(db: Session, bank_id: int) -> models.Bank:
    bank = db.query(models.Bank).filter(
        models.Bank.id == bank_id, models.Bank.company_id == db.info["company_id"]
    ).first()
    if bank is None:
        raise HTTPException(404, "البنك غير موجود")
    return bank


def _line(db: Session, bank_id: int, line_id: int) -> models.BankStatementLine:
    line = db.query(models.BankStatementLine).filter(
        models.BankStatementLine.id == line_id,
        models.BankStatementLine.bank_id == bank_id,
        models.BankStatementLine.company_id == db.info["company_id"],
    ).first()
    if line is None:
        raise HTTPException(404, "سطر الكشف غير موجود")
    return line


def _out(line: models.BankStatementLine) -> schemas.BankStatementLineOut:
    out = schemas.BankStatementLineOut.model_validate(line)
    out.matched_payment_reference = line.payment.reference if line.payment else None
    return out


@router.get("", response_model=List[schemas.BankStatementLineOut])
def list_lines(
    bank_id: int,
    unmatched_only: bool = False,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.BankStatementLine).filter(
        models.BankStatementLine.company_id == db.info["company_id"],
        models.BankStatementLine.bank_id == bank_id,
    )
    if unmatched_only:
        q = q.filter(models.BankStatementLine.matched_payment_id.is_(None))
    return [_out(l) for l in q.order_by(models.BankStatementLine.value_date, models.BankStatementLine.id).all()]


@router.post("/import", response_model=List[schemas.BankStatementLineOut], status_code=status.HTTP_201_CREATED)
async def import_statement(
    bank_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """استيراد كشف بنك CSV: أعمدة date/tarikh · description/وصف · amount/مبلغ · reference اختياري."""
    bank = _bank_in_company(db, bank_id)
    content = await file.read()
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise HTTPException(422, "الملف فارغ أو بلا صفوف")

    def pick(row: dict, names: List[str]) -> Optional[str]:
        for n in names:
            if n in row and str(row[n] or "").strip():
                return str(row[n]).strip()
        return None

    created: List[models.BankStatementLine] = []
    errors: List[str] = []
    for idx, row in enumerate(rows, start=2):
        raw_date = pick(row, ["date", "tarikh", "التاريخ"])
        raw_desc = pick(row, ["description", "وصف", "details"])
        raw_amount = pick(row, ["amount", "مبلغ", "قيمة"])
        raw_ref = pick(row, ["reference", "مرجع", "ref"])
        if raw_date is None and raw_amount is None:
            continue  # صف فارغ
        try:
            if raw_date is None:
                raise ValueError("التاريخ مفقود")
            d = None
            for fmt in _DATE_FORMATS:
                try:
                    d = datetime.strptime(raw_date, fmt).date()
                    break
                except ValueError:
                    continue
            if d is None:
                raise ValueError(f"صيغة تاريخ غير معروفة: {raw_date}")
            amount = Decimal(raw_amount.replace(",", "")) if raw_amount else None
            if amount is None or amount == 0:
                raise ValueError("المبلغ مفقود أو صفر")
        except (ValueError, InvalidOperation) as exc:
            errors.append(f"سطر {idx}: {exc}")
            continue
        line = models.BankStatementLine(
            company_id=db.info["company_id"],
            bank_id=bank.id,
            value_date=d,
            description=(raw_desc or "")[:500],
            amount=amount.quantize(Decimal("0.01")),
            reference=raw_ref[:200] if raw_ref else None,
            imported_by=user.id,
        )
        db.add(line)
        created.append(line)
    db.commit()
    for line in created:
        db.refresh(line)
    audit(db, user, "import", "bank_statement", bank.id,
          f"استيراد كشف «{bank.name}»: {len(created)} سطر · {len(errors)} خطأ")
    if errors and not created:
        raise HTTPException(422, "; ".join(errors[:5]))
    return [_out(l) for l in created]


@router.post("/{line_id}/match", response_model=schemas.BankStatementLineOut)
def match_line(
    bank_id: int,
    line_id: int,
    payload: schemas.BankStatementMatchIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """مطابقة سطر كشف مع سند (amount=None للفك)."""
    line = _line(db, bank_id, line_id)
    if payload.payment_id is None:
        line.matched_payment_id = None
        db.commit()
        audit(db, user, "update", "bank_statement", line.id, f"فك مطابقة سطر {line.id}")
        return _out(line)
    payment = db.query(models.Payment).filter(
        models.Payment.id == payload.payment_id,
        models.Payment.company_id == db.info["company_id"],
    ).first()
    if payment is None:
        raise HTTPException(404, "السند غير موجود")
    if payment.bank_id != bank_id:
        raise HTTPException(422, "السند ليس على نفس البنك")
    already = db.query(models.BankStatementLine).filter(
        models.BankStatementLine.matched_payment_id == payment.id
    ).first()
    if already is not None:
        raise HTTPException(409, f"السند مطابق مسبقًا لسطر الكشف #{already.id}")
    if abs(Decimal(str(payment.amount)) - abs(Decimal(str(line.amount)))) > Decimal("0.01"):
        raise HTTPException(422, f"المبلغ لا يطابق: سند {payment.amount} ↔ كشف {line.amount}")
    line.matched_payment_id = payment.id
    db.commit()
    audit(db, user, "update", "bank_statement", line.id, f"مطابقة سطر {line.id} مع سند {payment.id}")
    return _out(line)


@router.post("/auto-match")
def auto_match(
    bank_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """مطابقة آلية: كل سطر غير مطابق يُقابَل بالسند الفريد المطابق له
    (نفس البنك · نفس المبلغ ±0.01 · غير مطابق لسطر آخر · التاريخ ضمن نافذة 30 يومًا قبل/5 بعد).
    السندات المرشحة المتعددة (الغموض) تُتخطى."""
    from datetime import timedelta
    bank = _bank_in_company(db, bank_id)
    company_id = db.info["company_id"]
    unmatched = db.query(models.BankStatementLine).filter(
        models.BankStatementLine.company_id == company_id,
        models.BankStatementLine.bank_id == bank_id,
        models.BankStatementLine.matched_payment_id.is_(None),
    ).all()
    taken = {row.matched_payment_id for row in db.query(models.BankStatementLine).filter(
        models.BankStatementLine.company_id == company_id,
        models.BankStatementLine.bank_id == bank_id,
        models.BankStatementLine.matched_payment_id.isnot(None),
    ).all() if row.matched_payment_id}
    payments = db.query(models.Payment).filter(
        models.Payment.company_id == company_id,
        models.Payment.bank_id == bank_id,
        models.Payment.status == "posted",
    ).all()
    matched = 0
    skipped_ambiguous = 0
    for line in unmatched:
        lo = line.value_date - timedelta(days=30)
        hi = line.value_date + timedelta(days=5)
        candidates = [
            p for p in payments
            if p.id not in taken
            and p.paid_on is not None and lo <= p.paid_on <= hi
            and abs(Decimal(str(p.amount)) - abs(Decimal(str(line.amount)))) <= Decimal("0.01")
        ]
        if len(candidates) == 1:
            line.matched_payment_id = candidates[0].id  # type: ignore
            taken.add(candidates[0].id)  # type: ignore
            matched += 1
        elif len(candidates) > 1:
            skipped_ambiguous += 1
    db.commit()
    audit(db, user, "update", "bank_statement", bank.id,
          f"مطابقة آلية «{bank.name}»: {matched} مطابق · {skipped_ambiguous} غامض · {len(unmatched) - matched - skipped_ambiguous} بلا مرشح")
    return {"matched": matched, "ambiguous": skipped_ambiguous, "unmatched_left": len(unmatched) - matched - skipped_ambiguous}


@router.get("/summary", response_model=schemas.BankReconciliationSummary)
def reconciliation_summary(bank_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """ملخص المطابقة: صافي الكشف مقابل رصيد البنك الدفتري والفرق."""
    bank = _bank_in_company(db, bank_id)
    lines = db.query(models.BankStatementLine).filter(
        models.BankStatementLine.company_id == db.info["company_id"],
        models.BankStatementLine.bank_id == bank_id,
    ).all()
    statement_balance = sum((Decimal(str(l.amount)) for l in lines), Decimal("0"))
    matched_total = sum((Decimal(str(l.amount)) for l in lines if l.matched_payment_id), Decimal("0"))
    ledger_balance = Decimal("0")
    if bank.chart_account_id:
        acc = db.query(models.ChartAccount).filter(models.ChartAccount.id == bank.chart_account_id).first()
        ledger_balance = Decimal(str(acc.balance or 0)) if acc else Decimal("0")
    return schemas.BankReconciliationSummary(
        bank_id=bank.id,
        statement_balance=statement_balance.quantize(Decimal("0.01")),
        ledger_balance=ledger_balance.quantize(Decimal("0.01")),
        matched_total=matched_total.quantize(Decimal("0.01")),
        unmatched_count=sum(1 for l in lines if not l.matched_payment_id),
        difference=(statement_balance - ledger_balance).quantize(Decimal("0.01")),
    )


@router.delete("/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_line(
    bank_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    line = _line(db, bank_id, line_id)
    audit(db, user, "delete", "bank_statement", line.id, f"سطر {line.value_date} {line.amount}")
    db.delete(line)
    db.commit()
    return None
