from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy import func
from sqlalchemy.orm import Session
from .. import models, schemas, deps
from ..deps import get_current_user, require_manager
from ..audit import audit
from ..accounting import seed_default_coa
from ..codegen import unique_code
import csv
import io

router = APIRouter(prefix="/chart-of-accounts", tags=["Chart of Accounts"])

# ---------------------------------------------------------------- مطابقة أرصدة الشجرة مع دفتر الأستاذ
RECONCILE_TYPES_ASSET = ("asset", "expense")


def _reconcile_lines(db: Session, company_id: int):
    """لكل حساب: الرصيد المخزن مقابل صافي بنود دفتر الأستاذ والفرق بينهما."""
    accounts = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id).order_by(models.ChartAccount.code).all()
    sums = dict(db.query(
        models.JournalItem.account_id,
        func.coalesce(func.sum(models.JournalItem.debit - models.JournalItem.credit), 0)
    ).join(models.JournalEntry, models.JournalEntry.id == models.JournalItem.entry_id)
      .filter(models.JournalItem.company_id == company_id)
      .group_by(models.JournalItem.account_id).all())
    lines = []
    total_stored = total_ledger = total_drift = 0.0
    for acc in accounts:
        net = float(sums.get(acc.id, 0) or 0)
        ledger = net if acc.type in RECONCILE_TYPES_ASSET else -net
        stored = float(acc.balance or 0)
        if stored == 0 and ledger == 0:
            continue
        drift = round(stored - ledger, 2)
        lines.append((acc, stored, ledger, drift))
        total_stored += stored
        total_ledger += ledger
        total_drift += drift
    return lines, total_stored, total_ledger, total_drift


@router.get("/reconcile", response_model=schemas.ReconcileOut)
def reconcile_report(
    db: Session = Depends(deps.get_db),
    user = Depends(get_current_user),
):
    company_id = user.active_company_id
    lines, ts, tl, td = _reconcile_lines(db, company_id)
    return schemas.ReconcileOut(
        lines=[
            schemas.ReconcileLine(
                account_id=acc.id, code=acc.code, name=acc.name, type=acc.type,
                stored=round(stored, 2), ledger=round(ledger, 2), drift=drift,
            ) for acc, stored, ledger, drift in lines
        ],
        total_stored=round(ts, 2), total_ledger=round(tl, 2), total_drift=round(td, 2),
    )


@router.post("/reconcile/apply", response_model=schemas.ReconcileOut)
def apply_reconcile(
    db: Session = Depends(deps.get_db),
    user = Depends(require_manager),
):
    """تطبيق التسوية: إعادة بناء الرصيد المخزن لكل حساب من دفتر الأستاذ (يُسجل في سجل التدقيق)."""
    company_id = user.active_company_id
    lines, ts, tl, td = _reconcile_lines(db, company_id)
    changed = 0
    for acc, stored, ledger, drift in lines:
        if drift != 0:
            acc.balance = round(ledger, 2)
            changed += 1
    audit(
        db, user, "update", "account_reconcile", None,
        f"تسوية أرصدة شجرة الحسابات — {changed} حساب · إجمالي الفروق {round(td, 2)}",
    )
    db.commit()
    lines, ts, tl, td = _reconcile_lines(db, company_id)
    return schemas.ReconcileOut(
        lines=[
            schemas.ReconcileLine(
                account_id=acc.id, code=acc.code, name=acc.name, type=acc.type,
                stored=round(stored, 2), ledger=round(ledger, 2), drift=drift,
            ) for acc, stored, ledger, drift in lines
        ],
        total_stored=round(ts, 2), total_ledger=round(tl, 2), total_drift=round(td, 2),
    )


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
