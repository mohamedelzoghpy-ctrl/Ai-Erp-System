from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy import func
from sqlalchemy.orm import Session
from .. import models, schemas, deps
from ..deps import get_current_user, require_manager
from ..audit import audit
from ..accounting import seed_default_coa, AccountingEngine
from ..codegen import unique_code
import csv
import io

router = APIRouter(prefix="/chart-of-accounts", tags=["Chart of Accounts"])

# ---------------------------------------------------------------- مطابقة أرصدة الشجرة مع دفتر الأستاذ
RECONCILE_TYPES_ASSET = ("asset", "expense")
_TWO_PLACES = Decimal("0.01")
_ZERO = Decimal("0")


def _q(value) -> Decimal:
    """تقريب مبلغ إلى منزلتين بـ Decimal (البيانات قد تأتي Decimal من PG أو float من SQLite)."""
    return Decimal(str(value or 0)).quantize(_TWO_PLACES)


def _reconcile_lines(db: Session, company_id: int):
    """لكل حساب: الرصيد المخزن مقابل صافي بنود دفتر الأستاذ والفرق بينهما (Decimal)."""
    accounts = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id).order_by(models.ChartAccount.code).all()
    sums = dict(db.query(
        models.JournalItem.account_id,
        func.coalesce(func.sum(models.JournalItem.debit - models.JournalItem.credit), 0)
    ).join(models.JournalEntry, models.JournalEntry.id == models.JournalItem.entry_id)
      .filter(models.JournalItem.company_id == company_id)
      .group_by(models.JournalItem.account_id).all())
    lines = []
    total_stored = total_ledger = total_drift = _ZERO
    for acc in accounts:
        net = _q(sums.get(acc.id, 0))
        ledger = net if acc.type in RECONCILE_TYPES_ASSET else -net
        stored = _q(acc.balance)
        if stored == 0 and ledger == 0:
            continue
        drift = (stored - ledger).quantize(_TWO_PLACES)
        lines.append((acc, stored, ledger, drift))
        total_stored += stored
        total_ledger += ledger
        total_drift += drift
    return lines, total_stored, total_ledger, total_drift


def _reconcile_response(db: Session, company_id: int, changed: int = 0,
                        journal_entry_id: Optional[int] = None, cash_synced: int = 0) -> schemas.ReconcileOut:
    lines, ts, tl, td = _reconcile_lines(db, company_id)
    return schemas.ReconcileOut(
        lines=[
            schemas.ReconcileLine(
                account_id=acc.id, code=acc.code, name=acc.name, type=acc.type,
                stored=stored, ledger=ledger, drift=drift,
            ) for acc, stored, ledger, drift in lines
        ],
        total_stored=ts, total_ledger=tl, total_drift=td,
        changed=changed, journal_entry_id=journal_entry_id, cash_synced=cash_synced,
    )


@router.get("/reconcile", response_model=schemas.ReconcileOut)
def reconcile_report(
    db: Session = Depends(deps.get_db),
    user = Depends(get_current_user),
):
    company_id = user.active_company_id
    return _reconcile_response(db, company_id)


@router.post("/reconcile/apply", response_model=schemas.ReconcileOut)
def apply_reconcile(
    payload: Optional[schemas.ReconcileApplyIn] = None,
    db: Session = Depends(deps.get_db),
    user = Depends(require_manager),
):
    """تطبيق التسوية على الحسابات المختارة (أو كل المتنافرة):
    rebuild = إعادة بناء الرصيد المخزن من الدفتر · journal = ترحيل الفرق كقيد موزون على حساب مقابل.
    يُسجل في سجل التدقيق."""
    body = payload or schemas.ReconcileApplyIn()
    company_id = user.active_company_id
    lines, _, _, _ = _reconcile_lines(db, company_id)
    drifted = [(acc, stored, ledger, drift) for acc, stored, ledger, drift in lines if drift != 0]
    if body.account_ids is not None:
        wanted = set(body.account_ids)
        targets = [t for t in drifted if t[0].id in wanted]
        missing = wanted - {t[0].id for t in targets}
        if missing:
            raise HTTPException(status_code=400, detail=f"حسابات غير متنافرة أو غير موجودة: {sorted(missing)}")
    else:
        targets = drifted

    changed = 0
    journal_entry_id = None
    if targets:
        if body.mode == "rebuild":
            for acc, stored, ledger, drift in targets:
                acc.balance = ledger
                changed += 1
            audit(
                db, user, "update", "account_reconcile", None,
                f"تسوية شجرة الحسابات (إعادة بناء) — {changed} حساب",
            )
        else:  # journal — ترحيل الفروق كقيد واحد موزون
            if not body.counter_account_id:
                raise HTTPException(status_code=400, detail="يلزم تحديد الحساب المقابل في وضع ترحيل القيود")
            counter = db.query(models.ChartAccount).filter(
                models.ChartAccount.id == body.counter_account_id,
                models.ChartAccount.company_id == company_id,
            ).first()
            if not counter:
                raise HTTPException(status_code=400, detail="الحساب المقابل غير موجود")
            if counter.is_group:
                raise HTTPException(status_code=400, detail="لا يمكن الترحيل على حساب مجموعي")
            if counter.id in {t[0].id for t in targets}:
                raise HTTPException(status_code=400, detail="الحساب المقابل ضمن الحسابات المُسوّاة نفسها")
            groups = [t[0].code for t in targets if t[0].is_group]
            if groups:
                raise HTTPException(status_code=400, detail=f"حسابات مجموعية لا تقبل الترحيل: {groups}")

            # لكل حساب: البند الناقص من الدفتر ليطابق الرصيد المخزن
            pre_stored = {acc.id: stored for acc, stored, ledger, drift in targets}
            items = []
            total_debit = total_credit = _ZERO
            for acc, stored, ledger, drift in targets:
                amount = abs(drift)
                debit_side = (acc.type in RECONCILE_TYPES_ASSET) == (drift > 0)
                item = {"account_id": acc.id, "debit": _ZERO, "credit": _ZERO,
                        "notes": f"تسوية فرق {drift}"}
                item["debit" if debit_side else "credit"] = amount
                total_debit += item["debit"]
                total_credit += item["credit"]
                items.append(item)
            counter_net = total_credit - total_debit  # ما يوازن القيد
            if counter_net > 0:
                items.append({"account_id": counter.id, "debit": counter_net, "credit": _ZERO})
            elif counter_net < 0:
                items.append({"account_id": counter.id, "debit": _ZERO, "credit": -counter_net})

            entry = AccountingEngine.create_entry(
                db, company_id, user.id,
                "قيد تسوية أرصدة شجرة الحسابات", items, reference="RECONCILE",
            )
            journal_entry_id = entry.id
            # المحرك حدّث الرصيد المخزن لل-targets بالفعل — نعيده للرصيد المخزن الأصلي
            # (القيد رفع رصيد الدفتر ليساويه، فلا يجب أن يُحتسب مرتين)
            for acc, stored, ledger, drift in targets:
                acc.balance = pre_stored[acc.id]
                changed += 1
            audit(
                db, user, "update", "account_reconcile", None,
                f"تسوية شجرة الحسابات (قيد رقم {entry.id}) — {changed} حساب · مقابل {counter.code}",
            )
    db.commit()
    return _reconcile_response(db, company_id, changed=changed, journal_entry_id=journal_entry_id)


@router.post("/reconcile/sync-cash")
def sync_cash_balances(
    db: Session = Depends(deps.get_db),
    user = Depends(require_manager),
):
    """مزامنة أرصدة الخزائن والبنوك المتوازية مع أرصدة حساباتها في الشجرة (بعد التسوية)."""
    company_id = user.active_company_id
    acc_balances = {a.id: _q(a.balance) for a in db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id).all()}
    synced = 0
    for entity in (
        db.query(models.Safe).filter(models.Safe.company_id == company_id).all()
        + db.query(models.Bank).filter(models.Bank.company_id == company_id).all()
    ):
        target = acc_balances.get(entity.chart_account_id) if entity.chart_account_id else None
        if target is None or _q(entity.balance) == target:
            continue
        entity.balance = target
        synced += 1
    if synced:
        audit(
            db, user, "update", "cash_sync", None,
            f"مزامنة أرصدة الخزائن/البنوك مع الشجرة — {synced} كيان",
        )
    db.commit()
    return {"synced": synced}


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_accounts(
    file: UploadFile = File(...),
    db: Session = Depends(deps.get_db),
    user = Depends(get_current_user),
):
    company_id = user.active_company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="No active company selected")

    content = await file.read()
    csv_reader = csv.DictReader(io.StringIO(content.decode("utf-8")))

    imported_count = 0
    for row in csv_reader:
        # Expected columns: code, name, type, parent_id, is_group
        code = row.get("code")
        name = row.get("name")
        acc_type = row.get("type")
        parent_id = row.get("parent_id")
        is_group = row.get("is_group", "false").lower() == "true"

        if not code or not name or not acc_type:
            continue

        # Basic check to avoid duplicates
        existing = db.query(models.ChartAccount).filter(
            models.ChartAccount.company_id == company_id,
            models.ChartAccount.code == code
        ).first()

        if not existing:
            db_acc = models.ChartAccount(
                company_id=company_id,
                code=code,
                name=name,
                type=acc_type,
                parent_id=int(parent_id) if parent_id and parent_id.isdigit() else None,
                is_group=is_group
            )
            db.add(db_acc)
            imported_count += 1

    db.commit()
    return {"message": f"Successfully imported {imported_count} accounts"}

@router.post("/seed", status_code=status.HTTP_201_CREATED)
def seed_coa(
    db: Session = Depends(deps.get_db),
    user: models.User = Depends(deps.require_manager),
):
    company_id = db.info["company_id"]
    if not company_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No active company selected")
    created = seed_default_coa(db, company_id)
    # البذرة flush-only — الـendpoint يملك الـcommit الوحيد (قاعدة الذرية)
    db.commit()
    return {"created": created}


@router.post("/backfill-links")
def backfill_links(
    db: Session = Depends(deps.get_db),
    user: models.User = Depends(deps.require_manager),
):
    company_id = db.info["company_id"]
    if not company_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No active company selected")
    from ..accounting import seed_default_coa, link_safe_coa, link_bank_coa, link_party_coa, seed_default_cost_centers, seed_default_fiscal_year
    seed_default_coa(db, company_id)
    seed_default_cost_centers(db, company_id)
    seed_default_fiscal_year(db, company_id)
    linked = 0
    for s in db.query(models.Safe).filter(models.Safe.company_id == company_id).all():
        if not s.chart_account_id:
            link_safe_coa(db, s, company_id)
            if s.chart_account_id:
                linked += 1
    for b in db.query(models.Bank).filter(models.Bank.company_id == company_id).all():
        if not b.chart_account_id:
            link_bank_coa(db, b, company_id)
            if b.chart_account_id:
                linked += 1
    for sup in db.query(models.Supplier).filter(models.Supplier.company_id == company_id).all():
        if not sup.chart_account_id:
            link_party_coa(db, sup, company_id, is_customer=False)
            if sup.chart_account_id:
                linked += 1
    for cust in db.query(models.Customer).filter(models.Customer.company_id == company_id).all():
        if not cust.chart_account_id:
            link_party_coa(db, cust, company_id, is_customer=True)
            if cust.chart_account_id:
                linked += 1
    db.commit()
    return {"linked": linked}
@router.get("", response_model=List[schemas.ChartAccountOut])
def get_accounts(
    db: Session = Depends(deps.get_db),
    user = Depends(get_current_user),
):
    # Ensure the user is accessing data for their active company
    company_id = user.active_company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="No active company selected")

    return db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id).all()

@router.post("", response_model=schemas.ChartAccountOut, status_code=status.HTTP_201_CREATED)
def create_account(
    acc_in: schemas.ChartAccountCreate,
    db: Session = Depends(deps.get_db),
    user = Depends(get_current_user),
):
    company_id = user.active_company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="No active company selected")

    code = (acc_in.code or "").strip()
    if not code:
        prefix = (acc_in.type or "ACC")[:3].upper()
        code = unique_code(db, models.ChartAccount, company_id, acc_in.name, prefix, max_length=50)

    # Check if code already exists for this company
    existing = db.query(models.ChartAccount).filter(
        models.ChartAccount.company_id == company_id,
        models.ChartAccount.code == code
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Account code already exists for this company")

    data = acc_in.model_dump()
    data["code"] = code
    db_acc = models.ChartAccount(**data, company_id=company_id)
    db.add(db_acc)
    db.commit()
    db.refresh(db_acc)
    return db_acc

@router.put("/{id}", response_model=schemas.ChartAccountOut)
def update_account(
    id: int,
    acc_in: schemas.ChartAccountUpdate,
    db: Session = Depends(deps.get_db),
    user = Depends(get_current_user),
):
    company_id = user.active_company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="No active company selected")

    db_acc = db.query(models.ChartAccount).filter(
        models.ChartAccount.id == id,
        models.ChartAccount.company_id == company_id
    ).first()

    if not db_acc:
        raise HTTPException(status_code=404, detail="Account not found")

    for field, value in acc_in.model_dump(exclude_unset=True).items():
        setattr(db_acc, field, value)

    db.commit()
    db.refresh(db_acc)
    return db_acc


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    id: int,
    db: Session = Depends(deps.get_db),
    user = Depends(require_manager),
):
    """حذف حساب: مسموح فقط للفرعيات الخاملة بلا حركة دفترية ولا أبناء ولا روابط كيانات."""
    company_id = user.active_company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="No active company selected")

    acc = db.query(models.ChartAccount).filter(
        models.ChartAccount.id == id,
        models.ChartAccount.company_id == company_id,
    ).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")

    if db.query(models.ChartAccount).filter(models.ChartAccount.parent_id == id).count():
        raise HTTPException(status_code=409, detail="لا يمكن حذف حساب له حسابات فرعية")
    has_ledger = db.query(models.JournalItem.id).filter(
        models.JournalItem.account_id == id,
        models.JournalItem.company_id == company_id,
    ).first()
    if has_ledger:
        raise HTTPException(status_code=409, detail="الحساب عليه حركة دفترية — عطّله بدل حذفه")
    for model in (models.Safe, models.Bank, models.Customer, models.Supplier):
        if db.query(model.id).filter(model.chart_account_id == id).first():  # type: ignore[attr-defined]
            raise HTTPException(status_code=409, detail="الحساب مرتبط بخزينة/بنك/عميل/مورد — افصل الرابط أولًا")

    db.delete(acc)
    audit(db, user, "delete", "chart_account", id, f"حساب {acc.code} — {acc.name}")
    db.commit()
    return None


@router.post("/roll-up")
def roll_up_balances(
    db: Session = Depends(deps.get_db),
    user = Depends(require_manager),
):
    """إعادة احتساب أرصدة الحسابات المجموعية من أبنائها (الفرعيات تبقى مرجع الحقيقة)."""
    company_id = db.info["company_id"]
    if not company_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No active company selected")
    changed = AccountingEngine.roll_up_balances(db, company_id)
    audit(db, user, "update", "chart_account_rollup", None, f"إعادة احتساب {changed} حساب مجموعي")
    db.commit()
    return {"changed": changed}
