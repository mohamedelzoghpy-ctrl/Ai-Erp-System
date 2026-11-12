"""Fixed Assets — manage company assets, depreciation, and disposals.

Depreciation and disposal post real journal entries (expense 5240 vs accumulated
depreciation 1290; disposal: cash + accumulated depreciation vs asset cost, with a
gain/loss line), so the balance sheet and P&L stay correct for asset-heavy businesses.
"""
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..accounting import AccountingEngine, seed_default_coa
from ..audit import audit
from ..codegen import unique_code
from ..database import get_db
from ..deps import get_current_user, require_manager

router = APIRouter(
    prefix="/fixed-assets",
    tags=["fixed assets"],
    dependencies=[Depends(get_current_user)],
)

# شجرة الحسابات الافتراضية: مصروف الاستهلاك 5240 · مجمع الإهلاك 1290 · نقد 1111
DEPRECIATION_EXPENSE_CODE = "5240"
ACCUM_DEP_CODE = "1290"
CASH_ACC_CODE = "1111"
CAPITAL_ACC_CODE = "3100"  # رأس المال — مقابل رسملة الأصول المملوكة
GAIN_ACC_CODE = "4200"
LOSS_ACC_CODE = "5600"


def _asset_gl_account(db: Session, company_id: int, asset_type: str):
    """حساب الأصل حسب نوعه: مركبات 1220 · أثاث 1230 · غير ذلك معدات 1210."""
    t = (asset_type or "").strip().lower()
    if "مركب" in t or "vehicle" in t:
        code = "1220"
    elif "أثاث" in t or "furniture" in t:
        code = "1230"
    else:
        code = "1210"
    return _leaf_acc(db, company_id, code)


def _get_company_asset(db: Session, asset_id: int) -> models.FixedAsset:
    """جلب أصل مقيّدًا بالشركة (Session.get يتجاوز فلتر العزل)."""
    asset = (
        db.query(models.FixedAsset)
        .filter(models.FixedAsset.id == asset_id, models.FixedAsset.company_id == db.info["company_id"])
        .first()
    )
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    return asset


def _leaf_acc(db: Session, company_id: int, code: str):
    acc = db.query(models.ChartAccount).filter(
        models.ChartAccount.company_id == company_id, models.ChartAccount.code == code
    ).first()
    if acc is None or acc.is_group:
        return None
    return acc


@router.get("", response_model=List[schemas.FixedAssetOut])
def list_assets(
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    company_id = db.info["company_id"]
    q = db.query(models.FixedAsset).filter(models.FixedAsset.company_id == company_id)
    if is_active is not None:
        q = q.filter(models.FixedAsset.is_active == is_active)
    return q.order_by(models.FixedAsset.id).all()


@router.get("/{asset_id}", response_model=schemas.FixedAssetOut)
def get_asset(asset_id: int, db: Session = Depends(get_db)):
    return _get_company_asset(db, asset_id)


@router.post("", response_model=schemas.FixedAssetOut, status_code=status.HTTP_201_CREATED)
def create_asset(
    payload: schemas.FixedAssetCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    company_id = db.info["company_id"]
    code = (payload.code or "").strip() or unique_code(db, models.FixedAsset, company_id, payload.name, "AST", max_length=50)
    if db.query(models.FixedAsset).filter(
        models.FixedAsset.company_id == company_id,
        models.FixedAsset.code == code,
    ).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Asset code already exists")
    asset = models.FixedAsset(
        company_id=company_id,
        name=payload.name.strip(),
        code=code,
        asset_type=payload.asset_type,
        purchase_date=payload.purchase_date,
        cost=payload.cost,
        accumulated_depreciation=payload.accumulated_depreciation,
        current_book_value=payload.current_book_value,
        depreciation_method=payload.depreciation_method,
        useful_life_years=payload.useful_life_years,
        salvage_value=payload.salvage_value,
        is_active=payload.is_active,
    )
    db.add(asset)
    db.flush()

    # رسملة في الدفاتر: مدين حساب الأصل (1210/1220/1230) · دائن رأس المال 3100 —
    # بدونها يبقى الأصل خارج الميزانية ولا يصح قيد استبعاده لاحقًا.
    if payload.cost > 0:
        seed_default_coa(db, company_id)
        asset_acc = _asset_gl_account(db, company_id, payload.asset_type)
        capital_acc = _leaf_acc(db, company_id, CAPITAL_ACC_CODE)
        if asset_acc is None or capital_acc is None:
            raise HTTPException(409, "حسابات رسملة الأصول (1210/3100) غير موجودة في شجرة الحسابات")
        AccountingEngine.create_entry(
            db=db,
            company_id=company_id,
            user_id=user.id,
            description=f"Capitalization {asset.code} — {asset.name}",
            items=[
                {"account_id": asset_acc.id, "debit": payload.cost, "credit": 0},
                {"account_id": capital_acc.id, "debit": 0, "credit": payload.cost},
            ],
            reference=f"FA-C{asset.id}",
            date=payload.purchase_date,
        )
    db.commit()
    db.refresh(asset)
    audit(db, user, "create", "fixed_asset", asset, f"{asset.code} · {asset.name} · تكلفة {asset.cost}")
    return asset


@router.patch("/{asset_id}", response_model=schemas.FixedAssetOut)
def update_asset(
    asset_id: int,
    payload: schemas.FixedAssetUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    asset = _get_company_asset(db, asset_id)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        if value is not None:
            setattr(asset, key, value)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Asset code already exists or update violates a constraint",
        ) from exc
    db.refresh(asset)
    audit(db, user, "update", "fixed_asset", asset, ", ".join(data.keys()))
    return asset


@router.post("/{asset_id}/depreciate", response_model=schemas.FixedAssetOut)
def post_depreciation(
    asset_id: int,
    payload: schemas.FixedAssetDepreciateIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """Record a depreciation entry for an asset and post the matching journal:
    Debit مصروف الاستهلاك 5240 / Credit مجمع الإهلاك 1290."""
    asset = _get_company_asset(db, asset_id)
    if not asset.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "أصل غير نشط — لا يمكن إهلاكه")
    amount = payload.amount
    if amount <= 0:
        raise HTTPException(422, "Depreciation amount must be positive")
    if asset.current_book_value - amount < asset.salvage_value:
        raise HTTPException(422, "Depreciation exceeds salvage value")

    company_id = db.info["company_id"]
    seed_default_coa(db, company_id)
    expense_acc = _leaf_acc(db, company_id, DEPRECIATION_EXPENSE_CODE)
    accum_acc = _leaf_acc(db, company_id, ACCUM_DEP_CODE)
    if expense_acc is None or accum_acc is None:
        raise HTTPException(409, "حسابات الإهلاك (5240/1290) غير موجودة في شجرة الحسابات")

    asset.accumulated_depreciation += amount
    asset.current_book_value -= amount
    entry = AccountingEngine.create_entry(
        db=db,
        company_id=company_id,
        user_id=user.id,
        description=f"Depreciation {asset.code} — {asset.name}",
        items=[
            {"account_id": expense_acc.id, "debit": amount, "credit": 0},
            {"account_id": accum_acc.id, "debit": 0, "credit": amount},
        ],
        reference=f"FA-{asset.id}",
        date=payload.date,
    )
    db.commit()
    db.refresh(asset)
    audit(db, user, "depreciate", "fixed_asset", asset, f"Depreciation: {amount} · JE-{entry.id}")
    return asset


@router.post("/depreciate-all")
def depreciate_all_assets(
    payload: Optional[dict] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """إهلاك شهري مجمع لكل الأصول النشطة (قسط ثابت): قيد واحد للشهر مرجع FA-RUN-YYYY-MM.

    المبلغ الشهري = (التكلفة − المتخلف) ÷ العمر بالأشهر، محصورًا بعدم النزول تحت المتخلف.
    الأصول التي انتهت صلاحية إهلاكها تُتخطى. idempotent: تشغيلان في نفس الشهر → 409."""
    from datetime import date as _d

    body = payload or {}
    run_date = body.get("date")
    run_date = _d.fromisoformat(run_date) if isinstance(run_date, str) else _d.today()
    company_id = db.info["company_id"]
    ref = f"FA-RUN-{run_date.strftime('%Y-%m')}"
    exists = db.query(models.JournalEntry.id).filter(
        models.JournalEntry.company_id == company_id, models.JournalEntry.reference == ref
    ).first()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, f"تم ترحيل إهلاك الشهر بالفعل ({ref})")

    seed_default_coa(db, company_id)
    expense_acc = _leaf_acc(db, company_id, DEPRECIATION_EXPENSE_CODE)
    accum_acc = _leaf_acc(db, company_id, ACCUM_DEP_CODE)
    if expense_acc is None or accum_acc is None:
        raise HTTPException(409, "حسابات الإهلاك (5240/1290) غير موجودة في شجرة الحسابات")

    items: list = []
    details: list = []
    total = Decimal("0")
    for asset in db.query(models.FixedAsset).filter(
        models.FixedAsset.company_id == company_id, models.FixedAsset.is_active.is_(True)
    ).order_by(models.FixedAsset.id).all():
        months = max((asset.useful_life_years or 0) * 12, 1)
        monthly = ((asset.cost - (asset.salvage_value or Decimal("0"))) / Decimal(months)).quantize(Decimal("0.01"))
        headroom = asset.current_book_value - (asset.salvage_value or Decimal("0"))
        amount = min(monthly, headroom)
        if amount <= 0:
            continue
        asset.accumulated_depreciation += amount
        asset.current_book_value -= amount
        total += amount
        details.append(f"{asset.code}: {amount}")

    if total <= 0:
        return {"total": "0.00", "assets": 0, "entry_id": None, "detail": []}

    items = [
        {"account_id": expense_acc.id, "debit": total, "credit": 0},
        {"account_id": accum_acc.id, "debit": 0, "credit": total},
    ]
    entry = AccountingEngine.create_entry(
        db=db, company_id=company_id, user_id=user.id,
        description=f"Depreciation run {run_date.strftime('%Y-%m')}",
        items=items, reference=ref, date=run_date,
    )
    db.commit()
    audit(db, user, "depreciate", "fixed_asset_run", None,
          f"إهلاك شهري مجمع {run_date.strftime('%Y-%m')} — {len(details)} أصل · إجمالي {total} · JE-{entry.id}")
    return {"total": str(total), "assets": len(details), "entry_id": entry.id, "detail": details}


@router.post("/{asset_id}/dispose", response_model=schemas.FixedAssetOut)
def dispose_asset(
    asset_id: int,
    payload: schemas.FixedAssetDisposeIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """Dispose of an asset with the standard full journal (asset was capitalized at creation):
    Debit cash (proceeds) + accumulated depreciation, Credit asset cost, plus a
    gain (4200) / loss (5600) line for the difference — always balanced."""
    asset = _get_company_asset(db, asset_id)
    if not asset.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "الأصل مُستبعد بالفعل")
    company_id = db.info["company_id"]
    seed_default_coa(db, company_id)

    book_value = asset.current_book_value or Decimal("0")
    proceeds = payload.disposal_proceeds or Decimal("0")
    accum_amount = asset.accumulated_depreciation or Decimal("0")
    asset_acc = _asset_gl_account(db, company_id, asset.asset_type)
    accum_acc = _leaf_acc(db, company_id, ACCUM_DEP_CODE)
    if asset_acc is None or accum_acc is None:
        raise HTTPException(409, "حسابات الأصول (1210/1290) غير موجودة في شجرة الحسابات")

    cash_acc = None
    safe = bank = None
    if payload.safe_id is not None:
        safe = db.query(models.Safe).filter(
            models.Safe.id == payload.safe_id, models.Safe.company_id == company_id
        ).first()
        if safe is None:
            raise HTTPException(422, "الخزينة غير موجودة")
        cash_acc = (
            db.query(models.ChartAccount).filter(
                models.ChartAccount.id == safe.chart_account_id, models.ChartAccount.company_id == company_id
            ).first() if safe.chart_account_id else None
        )
        if cash_acc is None or cash_acc.is_group:
            raise HTTPException(422, "الخزينة غير مرتبطة بحساب محاسبي — استخدم ربط الكيانات أولًا")
    elif payload.bank_id is not None:
        bank = db.query(models.Bank).filter(
            models.Bank.id == payload.bank_id, models.Bank.company_id == company_id
        ).first()
        if bank is None:
            raise HTTPException(422, "البنك غير موجود")
        cash_acc = (
            db.query(models.ChartAccount).filter(
                models.ChartAccount.id == bank.chart_account_id, models.ChartAccount.company_id == company_id
            ).first() if bank.chart_account_id else None
        )
        if cash_acc is None or cash_acc.is_group:
            raise HTTPException(422, "البنك غير مرتبط بحساب محاسبي — استخدم ربط الكيانات أولًا")
    elif proceeds > 0:
        cash_acc = _leaf_acc(db, company_id, CASH_ACC_CODE)
        if cash_acc is None:
            raise HTTPException(409, f"حساب النقد {CASH_ACC_CODE} غير موجود لاستلام عائدات البيع")

    items: list = []
    if proceeds > 0:
        items.append({"account_id": cash_acc.id, "debit": proceeds, "credit": 0})
    if accum_amount > 0:
        items.append({"account_id": accum_acc.id, "debit": accum_amount, "credit": 0})
    if book_value > proceeds:
        loss_acc = _leaf_acc(db, company_id, LOSS_ACC_CODE)  # خسارة استبعاد
        if loss_acc is None:
            raise HTTPException(409, f"حساب الخسارة ({LOSS_ACC_CODE}) غير موجود في شجرة الحسابات")
        items.append({"account_id": loss_acc.id, "debit": book_value - proceeds, "credit": 0})
    elif proceeds > book_value:
        gain_acc = _leaf_acc(db, company_id, GAIN_ACC_CODE)  # ربح استبعاد
        if gain_acc is None:
            raise HTTPException(409, f"حساب الربح ({GAIN_ACC_CODE}) غير موجود في شجرة الحسابات")
        items.append({"account_id": gain_acc.id, "debit": 0, "credit": proceeds - book_value})
    items.append({"account_id": asset_acc.id, "debit": 0, "credit": asset.cost})

    asset.is_active = False
    entry = AccountingEngine.create_entry(
        db=db,
        company_id=company_id,
        user_id=user.id,
        description=f"Disposal {asset.code} — {asset.name}",
        items=items,
        reference=f"FA-D{asset.id}",
        date=payload.date,
    )
    if proceeds > 0 and safe is not None:
        safe.balance = (safe.balance or 0) + proceeds
    if proceeds > 0 and bank is not None:
        bank.balance = (bank.balance or 0) + proceeds
    db.commit()
    db.refresh(asset)
    audit(db, user, "dispose", "fixed_asset", asset,
          f"استبعاد · قيمة دفترية {book_value} · عائدات {proceeds} · JE-{entry.id}")
    return asset


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(asset_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    asset = _get_company_asset(db, asset_id)
    db.delete(asset)
    db.commit()
    audit(db, user, "delete", "fixed_asset", asset_id, f"asset {asset_id}")
