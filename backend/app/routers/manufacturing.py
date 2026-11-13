"""التصنيع: قوائم المواد (BOM) بمسار تشغيل مراحل + أوامر التصنيع بصرف مرحلي وإنتاج دفعات وقيود تلقائية.

دورة أمر التصنيع: draft -> (issue: صرف + قيد WIP) -> in_progress -> (produce batches) -> completed
الكميات عشرية (NUMERIC 12,3)، والعمليات الحساسة مأمونة بأقفال صفوف وقيود فريدة (منع التكرار).
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
import os

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas, stock
from ..accounting import AccountingEngine, link_party_coa, seed_default_coa
from ..audit import audit
from ..codegen import unique_code
from ..database import get_db
from ..deps import get_current_user, require_manager
from ..pagination import paginate
from ..stock import available as stock_available
from ..stock import dec, move_stock, q3

boms = APIRouter(prefix="/boms", tags=["manufacturing"], dependencies=[Depends(get_current_user)])
production_orders = APIRouter(prefix="/production-orders", tags=["manufacturing"], dependencies=[Depends(get_current_user)])
work_centers = APIRouter(prefix="/work-centers", tags=["manufacturing"], dependencies=[Depends(get_current_user)])

WIP_CODE = "1130"       # إنتاج تحت التشغيل
INVENTORY_CODE = "1101"  # المخزون
VARIANCE_CODE = "5600"   # مصاريف متنوعة (فروق تصنيع)
SCRAP_CODE = "5600"      # مصروف الهالك (نفس حساب الفروق)


# ---------------------------------------------------------------- helpers
def _account_id_by_code(db: Session, company_id: int, code: str) -> int:
    seed_default_coa(db, company_id)
    acc = db.query(models.ChartAccount).filter(
        models.ChartAccount.company_id == company_id, models.ChartAccount.code == code
    ).first()
    if acc is None:
        raise HTTPException(422, f"حساب {code} غير موجود في شجرة الحسابات")
    return acc.id


def _locked_po_or_404(db: Session, order_id: int) -> models.ProductionOrder:
    """أمر التصنيع مع قفل صفه (SELECT FOR UPDATE) — على Postgres يمنع سباق الصرف/الإنتاج المزدوج؛ يُتجاهل على SQLite."""
    po = (
        db.query(models.ProductionOrder)
        .filter(
            models.ProductionOrder.id == order_id,
            models.ProductionOrder.company_id == db.info["company_id"],
        )
        .with_for_update()
        .first()
    )
    if po is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Production order {order_id} not found")
    return po


def _bom_out(db: Session, bom: models.Bom) -> models.Bom:
    for item in bom.items:
        item.component_name = item.component.name if item.component else None  # type: ignore[attr-defined]
        item.component_code = item.component.sku if item.component else None  # type: ignore[attr-defined]
        item.component_unit = item.component.unit if item.component else None  # type: ignore[attr-defined]
    for op in bom.operations:
        op.work_center_name = op.work_center.name if op.work_center else None  # type: ignore[attr-defined]
    return bom


def _po_out(po: models.ProductionOrder) -> models.ProductionOrder:
    po.product_name = po.product.name if po.product else None  # type: ignore[attr-defined]
    po.raw_warehouse_name = po.raw_warehouse.name if po.raw_warehouse else None  # type: ignore[attr-defined]
    po.output_warehouse_name = po.output_warehouse.name if po.output_warehouse else None  # type: ignore[attr-defined]
    po.subcontractor_name = po.subcontractor.name if po.subcontractor else None  # type: ignore[attr-defined]
    po.production_line_name = po.production_line.name if po.production_line else None  # type: ignore[attr-defined]
    po.is_late = bool(
        po.scheduled_date
        and po.status in ("draft", "in_progress")
        and po.scheduled_date < date.today()
    )  # type: ignore[attr-defined]
    return po


def _po_full_out(po: models.ProductionOrder) -> models.ProductionOrder:
    _consumptions_out(po)
    for op in po.operations:
        op.work_center_name = op.work_center.name if op.work_center else None  # type: ignore[attr-defined]
    # costs_total تُحسب تلقائيًا من property الموديل عند التسلسل
    return _po_out(po)


def _consumptions_out(po: models.ProductionOrder) -> models.ProductionOrder:
    for c in po.consumptions:
        c.component_name = c.component.name if c.component else None  # type: ignore[attr-defined]
        c.component_unit = c.component.unit if c.component else None  # type: ignore[attr-defined]
    return po


def _bom_window_query(db: Session, company_id: int, product_id: int, on_date):
    """القوائم المفعّلة التي يشمل تاريخ الأمر فترتها (NULL في السريان = دائمة)."""
    q = db.query(models.Bom).filter(
        models.Bom.company_id == company_id,
        models.Bom.product_id == product_id,
        models.Bom.is_active.is_(True),
    )
    if on_date is not None:
        q = q.filter(
            or_(models.Bom.valid_from.is_(None), models.Bom.valid_from <= on_date),
            or_(models.Bom.valid_to.is_(None), models.Bom.valid_to >= on_date),
        )
    return q.order_by(models.Bom.id.desc())


def _active_bom(db: Session, company_id: int, product_id: int) -> models.Bom:
    bom = _bom_window_query(db, company_id, product_id, date.today()).first()
    if bom is None or not bom.items:
        raise HTTPException(422, "لا توجد قائمة مواد (BOM) مفعّلة وسارية لهذا المنتج — أنشئها أولًا")
    return bom


def _snapshot_operations(db: Session, company_id: int, po: models.ProductionOrder, bom: models.Bom) -> int:
    """نسخ مسار التشغيل من قائمة المواد إلى أمر التشغيل (مراحل بالتسلسل). تُستدعى مرة عند الإنشاء."""
    if not bom.operations:
        return 0
    for op in bom.operations:
        db.add(models.ProductionOrderOperation(
            company_id=company_id,  # type: ignore
            order_id=po.id,  # type: ignore
            seq=op.seq,
            name=op.name,
            work_center_id=op.work_center_id,
            run_minutes_per_unit=op.run_minutes_per_unit,
        ))
    return len(bom.operations)


def _snapshot_items(db: Session, company_id: int, po: models.ProductionOrder, bom: models.Bom) -> Decimal:
    """نسخ بنود قائمة المواد إلى أمر التشغيل + حساب التكلفة القياسية للوحدة من أسعار الخامات وقت الإنشاء.

    التعديل على القائمة بعد إنشاء الأمر لا يغيّر متطلبات الأمر (الأوامر القديمة تظل كما خُطط لها).
    """
    std_total = Decimal("0")
    output_qty = max(dec(bom.output_qty), Decimal("1"))
    for item in bom.items:
        component = db.get(models.Product, item.component_id)
        std_total += dec(item.qty_per_output) * (1 + dec(item.scrap_pct) / 100) * dec(component.cost_price if component else 0)  # type: ignore[union-attr]
        db.add(models.ProductionOrderItem(
            company_id=company_id,  # type: ignore
            order_id=po.id,  # type: ignore
            component_id=item.component_id,  # type: ignore
            qty_per_output=item.qty_per_output,  # type: ignore
            scrap_pct=item.scrap_pct,  # type: ignore
            operation_seq=item.operation_seq,  # type: ignore
            notes=item.notes,  # type: ignore
        ))
    return (std_total / output_qty).quantize(Decimal("0.0001"))


def _validate_bom_operations(db: Session, company_id: int, operations: List[schemas.BomOperationIn]) -> None:
    seqs = [op.seq for op in operations]
    if len(seqs) != len(set(seqs)):
        raise HTTPException(422, "لا يمكن تكرار نفس رقم المرحلة")
    for op in operations:
        if op.work_center_id is not None:
            wc = db.get(models.WorkCenter, op.work_center_id)
            if wc is None or wc.company_id != company_id:
                raise HTTPException(422, f"مركز التشغيل {op.work_center_id} غير موجود")


def _materials_cost(order: models.ProductionOrder) -> Decimal:
    return sum((dec(c.qty) * c.unit_cost for c in order.consumptions), Decimal("0")).quantize(Decimal("0.01"))


def _costs_total(order: models.ProductionOrder) -> Decimal:
    return sum((dec(c.amount or 0) for c in order.costs), Decimal("0")).quantize(Decimal("0.01"))


def _total_cost(order: models.ProductionOrder) -> Decimal:
    return _materials_cost(order) + _costs_total(order)


def _wip_residual(db: Session, order: models.ProductionOrder) -> Decimal:
    """الرصيد المتبقي في WIP لهذا الأمر = (خامات + أجور) − دفعات − هالك مُرحّل.

    هذا هو المبلغ الوحيد الصحيح لقيد الفروق عند الإغلاق — يضمن أن WIP يُصفَّر تمامًا
    حتى مع هالك مرحلي أو تكاليف أُضيفت بين الدفعات. تُقرأ الدفعات من القاعدة مباشرة
    (وليس من العلاقة المخزّنة) حتى لا يفوتك الدفعة المضافة للتو في نفس الجلسة.
    """
    batches_total = db.query(
        func.coalesce(func.sum(models.ProductionBatch.cost), 0)
    ).filter(models.ProductionBatch.order_id == order.id).scalar()
    return (_total_cost(order) - dec(batches_total) - dec(order.scrap_cost)).quantize(Decimal("0.01"))


def _post_variance(db: Session, po: models.ProductionOrder, user: models.User, amount: Decimal, description: str) -> None:
    """ترحيل فروق التصنيع: موجب = مدين مصاريف متنوعة/دائن WIP، سالب = عكسه."""
    if amount == 0:
        return
    company_id = db.info["company_id"]
    variance_acc = _account_id_by_code(db, company_id, VARIANCE_CODE)
    wip_acc = _account_id_by_code(db, company_id, WIP_CODE)
    AccountingEngine.create_entry(
        db=db,
        company_id=company_id,
        user_id=user.id,
        description=description,
        items=(
            [
                {"account_id": variance_acc, "debit": amount, "credit": 0},
                {"account_id": wip_acc, "debit": 0, "credit": amount},
            ] if amount > 0 else
            [
                {"account_id": wip_acc, "debit": -amount, "credit": 0},
                {"account_id": variance_acc, "debit": 0, "credit": -amount},
            ]
        ),
        reference=po.code,
    )


def _check_warehouse_access(db: Session, user: models.User, *warehouse_ids: int) -> None:
    """منع الصرف/الإنتاج من مخازن خارج نطاق صلاحيات المستخدم (المديرون لهم كل المخازن)."""
    allowed = db.info.get("warehouse_ids") or ()
    if not allowed:
        return  # لا قيود مخازن مضبوطة لهذا المستخدم
    for wid in warehouse_ids:
        if wid and wid not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "لا تملك صلاحية على مخزن هذا الأمر")


COST_ACCOUNT = {"labor": "2140", "overhead": "2120"}  # رواتب مستحقة / مصاريف مستحقة
COST_LABEL = {"labor": "أجور تشغيل", "overhead": "أعباء غير مباشرة", "subcontract": "تكلفة تصنيع خارجي"}


# ---------------------------------------------------------------- BOMs
@boms.get("", response_model=List[schemas.BomOut])
def list_boms(
    product_id: Optional[int] = None,
    active_only: bool = False,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.Bom).filter(models.Bom.company_id == db.info["company_id"])
    if product_id is not None:
        q = q.filter(models.Bom.product_id == product_id)
    if active_only:
        q = q.filter(models.Bom.is_active.is_(True))
    rows = q.order_by(models.Bom.id.desc()).all()
    return [_bom_out(db, b) for b in rows]


@boms.post("", response_model=schemas.BomOut, status_code=status.HTTP_201_CREATED)
def create_bom(payload: schemas.BomCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    company_id = db.info["company_id"]
    product = db.get(models.Product, payload.product_id)
    if product is None or product.company_id != company_id:
        raise HTTPException(422, "المنتج غير موجود")
    if any(item.component_id == payload.product_id for item in payload.items):
        raise HTTPException(422, "المنتج النهائي لا يمكن أن يكون مكوّنًا في قائمته")
    component_ids = [item.component_id for item in payload.items]
    if len(component_ids) != len(set(component_ids)):
        raise HTTPException(422, "لا يمكن تكرار نفس المكوّن في القائمة")
    for cid in component_ids:
        comp = db.get(models.Product, cid)
        if comp is None or comp.company_id != company_id:
            raise HTTPException(422, f"المكوّن {cid} غير موجود")
    version = payload.version.strip() or "v1"
    dup = db.query(models.Bom).filter(
        models.Bom.company_id == company_id,
        models.Bom.product_id == payload.product_id,
        models.Bom.version == version,
    ).first()
    if dup is not None:
        raise HTTPException(422, f"الإصدار «{version}» موجود بالفعل للمنتج «{product.name}» — اختر إصدارًا آخر أو عدّل القائمة القائمة")
    if payload.is_active:
        # تفعيل إصدار واحد لكل منتج: أوقف إصدارات المنتج الأخرى
        db.query(models.Bom).filter(
            models.Bom.company_id == company_id,
            models.Bom.product_id == payload.product_id,
            models.Bom.is_active.is_(True),
        ).update({"is_active": False}, synchronize_session=False)
    _validate_bom_operations(db, company_id, payload.operations)
    op_seqs = {op.seq for op in payload.operations}
    for item in payload.items:
        if item.operation_seq is not None and item.operation_seq not in op_seqs:
            raise HTTPException(422, f"المكوّن مرتبط بمرحلة {item.operation_seq} غير موجودة في مسار التشغيل")

    if payload.valid_from and payload.valid_to and payload.valid_from > payload.valid_to:
        raise HTTPException(422, "بداية السريان بعد نهايته")
    bom = models.Bom(
        company_id=company_id,  # type: ignore
        product_id=payload.product_id,  # type: ignore
        version=payload.version.strip() or "v1",  # type: ignore
        output_qty=int(payload.output_qty),  # type: ignore
        is_active=payload.is_active,  # type: ignore
        valid_from=payload.valid_from,  # type: ignore
        valid_to=payload.valid_to,  # type: ignore
        notes=payload.notes,  # type: ignore
        created_by=user.id,  # type: ignore
    )
    db.add(bom)
    db.flush()
    for item in payload.items:
        db.add(models.BomItem(
            company_id=company_id,  # type: ignore
            bom_id=bom.id,  # type: ignore
            component_id=item.component_id,  # type: ignore
            qty_per_output=item.qty_per_output,  # type: ignore
            scrap_pct=item.scrap_pct,  # type: ignore
            operation_seq=item.operation_seq,  # type: ignore
            notes=item.notes,  # type: ignore
        ))
    for op in payload.operations:
        db.add(models.BomOperation(
            company_id=company_id,  # type: ignore
            bom_id=bom.id,  # type: ignore
            seq=op.seq,
            name=op.name.strip(),
            work_center_id=op.work_center_id,
            run_minutes_per_unit=q3(op.run_minutes_per_unit),  # type: ignore
            notes=op.notes,
        ))
    db.commit()
    db.refresh(bom)
    audit(db, user, "create", "bom", bom, f"{product.name} · {bom.version} · {len(payload.items)} مكوّن · {len(payload.operations)} مرحلة")
    db.refresh(bom)
    return _bom_out(db, bom)


@boms.get("/{bom_id}", response_model=schemas.BomOut)
def get_bom(bom_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    bom = db.get(models.Bom, bom_id)
    if bom is None or bom.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"BOM {bom_id} not found")
    return _bom_out(db, bom)


@boms.post("/{bom_id}/copy", response_model=schemas.BomOut, status_code=status.HTTP_201_CREATED)
def copy_bom(
    bom_id: int,
    payload: schemas.BomCopyIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """نسخ قائمة مواد إلى إصدار جديد: بنود ومسار تشغيل مطابقان — أساس تعديل القوائم دون فقدان التاريخ."""
    company_id = db.info["company_id"]
    src_bom = db.get(models.Bom, bom_id)
    if src_bom is None or src_bom.company_id != company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"BOM {bom_id} not found")
    version = (payload.version or "").strip()
    if not version:
        existing = db.query(models.Bom).filter(
            models.Bom.company_id == company_id, models.Bom.product_id == src_bom.product_id
        ).all()
        n = len(existing) + 1
        while any(b.version == f"v{n}" for b in existing):
            n += 1
        version = f"v{n}"
    dup = db.query(models.Bom).filter(
        models.Bom.company_id == company_id,
        models.Bom.product_id == src_bom.product_id,
        models.Bom.version == version,
    ).first()
    if dup is not None:
        raise HTTPException(422, f"الإصدار «{version}» موجود بالفعل للمنتج — اختر إصدارًا آخر")
    if payload.is_active:
        db.query(models.Bom).filter(
            models.Bom.company_id == company_id,
            models.Bom.product_id == src_bom.product_id,
            models.Bom.is_active.is_(True),
        ).update({"is_active": False}, synchronize_session=False)
    new_bom = models.Bom(
        company_id=company_id,  # type: ignore
        product_id=src_bom.product_id,  # type: ignore
        version=version,  # type: ignore
        output_qty=src_bom.output_qty,  # type: ignore
        is_active=payload.is_active,  # type: ignore
        notes=src_bom.notes,  # type: ignore
        created_by=user.id,
    )
    db.add(new_bom)
    db.flush()
    for it in src_bom.items:
        db.add(models.BomItem(
            company_id=company_id, bom_id=new_bom.id, component_id=it.component_id,
            qty_per_output=it.qty_per_output, scrap_pct=it.scrap_pct, operation_seq=it.operation_seq, notes=it.notes,
        ))
    for op in src_bom.operations:
        db.add(models.BomOperation(
            company_id=company_id, bom_id=new_bom.id, seq=op.seq, name=op.name,
            work_center_id=op.work_center_id, run_minutes_per_unit=op.run_minutes_per_unit, notes=op.notes,
        ))
    db.commit()
    db.refresh(new_bom)
    audit(db, user, "copy", "bom", new_bom, f"نسخ {src_bom.version} → {new_bom.version}")
    return _bom_out(db, new_bom)


@boms.get("/{bom_id}/cost-rollup", response_model=schemas.BomCostRollupOut)
def bom_cost_rollup(bom_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """التكلفة المعيارية المجمّعة للقائمة عبر كل المستويات: المكوّن له قائمة سارية تُستخدم
    تكلفته المجمّعة (لكل وحدة ناتج) وإلا تكلفة شرائه المسجلة — مع كشف الدوران."""
    company_id = db.info["company_id"]
    bom = db.get(models.Bom, bom_id)
    if bom is None or bom.company_id != company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "قائمة المواد غير موجودة")

    rollup_cache: dict = {}

    def component_unit_cost(pid: int, chain: tuple) -> Decimal:
        if pid in chain:
            raise HTTPException(422, "قوائم المواد دائرية — لا يمكن حساب التكلفة المجمّعة")
        if pid in rollup_cache:
            return rollup_cache[pid]
        child = _bom_window_query(db, company_id, pid, date.today()).first()
        if child is not None and child.id != bom_id and child.items:
            cost = _bom_unit_cost(child, chain + (pid,))
            rollup_cache[pid] = cost
            return cost
        comp = db.get(models.Product, pid)
        cost = dec(comp.cost_price) if comp else Decimal("0")
        rollup_cache[pid] = cost
        return cost

    def _bom_unit_cost(b: models.Bom, chain: tuple) -> Decimal:
        output = max(dec(b.output_qty), Decimal("1"))
        total = Decimal("0")
        for item in b.items:
            uc = component_unit_cost(item.component_id, chain)
            total += dec(item.qty_per_output) * (1 + dec(item.scrap_pct) / 100) * uc
        return (total / output).quantize(Decimal("0.0001"))

    lines = []
    total = Decimal("0")
    for item in bom.items:
        comp = db.get(models.Product, item.component_id)
        child = _bom_window_query(db, company_id, item.component_id, date.today()).first()
        if child is not None and child.id != bom.id and child.items:
            source = "own_bom"
            uc = component_unit_cost(item.component_id, (bom.product_id,))
        else:
            source = "cost_price"
            uc = component_unit_cost(item.component_id, (bom.product_id,))
        line_cost = (dec(item.qty_per_output) * (1 + dec(item.scrap_pct) / 100) * uc).quantize(Decimal("0.0001"))
        total += line_cost
        lines.append(schemas.BomCostRollupLine(
            component_id=item.component_id, component_name=comp.name if comp else None,
            qty_per_output=dec(item.qty_per_output), scrap_pct=dec(item.scrap_pct),
            source=source, unit_cost=uc.quantize(Decimal("0.0001")), line_cost=line_cost,
        ))
    output = max(dec(bom.output_qty), Decimal("1"))
    return schemas.BomCostRollupOut(
        bom_id=bom.id, product_id=bom.product_id, product_name=bom.product.name if bom.product else None,
        output_qty=dec(bom.output_qty), unit_cost=(total / output).quantize(Decimal("0.0001")), lines=lines,
    )


@boms.get("/{bom_id}/mrp-simulate")
def simulate_bom_mrp(
    bom_id: int,
    qty_planned: float = Query(gt=0, description="الكمية المخطط إنتاجها"),
    raw_warehouse_id: Optional[int] = Query(default=None, description="مخزن الخامات (اختياري)"),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """محاكي تخطيط الاحتياجات من المواد (MRP Simulation):
    يفكك بنود شجرة المواد للكمية المخططة ويقارنها بالرصيد المتاح حالياً في المخزن
    ويحدد بدقة الكمية المطلوبة، المتوفرة، العجز الصافي، والتكلفة التقديرية للشراء."""
    company_id = db.info["company_id"]
    bom = db.get(models.Bom, bom_id)
    if bom is None or bom.company_id != company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"BOM {bom_id} not found")
    
    out_qty = max(dec(bom.output_qty), Decimal("1"))
    ratio = dec(qty_planned) / out_qty

    lines = []
    total_shortage_cost = Decimal("0")
    has_shortage = False

    for item in sorted(bom.items, key=lambda it: it.id):
        component = db.get(models.Product, item.component_id)
        if component is None:
            continue
        
        # الكمية المطلوبة شاملة نسبة الهالك المتوقعة في الـ BOM
        scrap_mult = 1 + (dec(item.scrap_pct) / Decimal("100"))
        required = q3(dec(item.qty_per_output) * scrap_mult * ratio)
        
        # الرصيد المتاح حالياً
        if raw_warehouse_id is not None:
            avail = stock.available(db, component.id, raw_warehouse_id)
        else:
            avail = stock.total_available(db, component.id)
        avail = q3(avail)

        shortage = q3(max(Decimal("0"), required - avail))
        unit_cost = dec(component.cost_price or 0)
        est_cost = q3(shortage * unit_cost)
        if shortage > 0:
            has_shortage = True
            total_shortage_cost += est_cost

        lines.append({
            "component_id": component.id,
            "component_name": component.name,
            "component_sku": component.sku,
            "unit": component.unit or "وحدة",
            "qty_per_output": float(item.qty_per_output),
            "scrap_pct": float(item.scrap_pct),
            "required_qty": float(required),
            "available_qty": float(avail),
            "shortage_qty": float(shortage),
            "unit_cost": float(unit_cost),
            "estimated_purchase_cost": float(est_cost),
            "has_shortage": shortage > 0,
        })

    return {
        "bom_id": bom.id,
        "product_id": bom.product_id,
        "product_name": bom.product.name if bom.product else None,
        "bom_version": bom.version,
        "qty_planned": float(qty_planned),
        "warehouse_id": raw_warehouse_id,
        "can_produce_immediately": not has_shortage,
        "total_shortage_cost": float(total_shortage_cost),
        "items": lines,
    }


@boms.patch("/{bom_id}", response_model=schemas.BomOut)
def update_bom(bom_id: int, payload: schemas.BomCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    bom = db.get(models.Bom, bom_id)
    if bom is None or bom.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"BOM {bom_id} not found")
    if payload.product_id != bom.product_id:
        used = db.query(models.ProductionOrder).filter(models.ProductionOrder.bom_id == bom.id).count()
        if used:
            raise HTTPException(status.HTTP_409_CONFLICT, "لا يمكن تغيير منتج قائمة مستخدمة في أوامر تصنيع — أنشئ قائمة جديدة للمنتج الآخر")
    product = db.get(models.Product, payload.product_id)
    if product is None or product.company_id != db.info["company_id"]:
        raise HTTPException(422, "المنتج غير موجود")
    if any(item.component_id == payload.product_id for item in payload.items):
        raise HTTPException(422, "المنتج النهائي لا يمكن أن يكون مكوّنًا في قائمته")
    component_ids = [item.component_id for item in payload.items]
    if len(component_ids) != len(set(component_ids)):
        raise HTTPException(422, "لا يمكن تكرار نفس المكوّن في القائمة")
    new_version = payload.version.strip() or bom.version
    dup = db.query(models.Bom).filter(
        models.Bom.company_id == bom.company_id,
        models.Bom.product_id == payload.product_id,
        models.Bom.version == new_version,
        models.Bom.id != bom.id,
    ).first()
    if dup is not None:
        raise HTTPException(422, f"الإصدار «{new_version}» مستخدم بالفعل في قائمة أخرى لنفس المنتج — اختر إصدارًا آخر")
    if payload.is_active and not bom.is_active:
        db.query(models.Bom).filter(
            models.Bom.company_id == db.info["company_id"],
            models.Bom.product_id == payload.product_id,
            models.Bom.id != bom.id,
            models.Bom.is_active.is_(True),
        ).update({"is_active": False}, synchronize_session=False)
    _validate_bom_operations(db, bom.company_id, payload.operations)
    op_seqs = {op.seq for op in payload.operations}
    for item in payload.items:
        if item.operation_seq is not None and item.operation_seq not in op_seqs:
            raise HTTPException(422, f"المكوّن مرتبط بمرحلة {item.operation_seq} غير موجودة في مسار التشغيل")

    bom.product_id = payload.product_id  # type: ignore
    bom.version = payload.version.strip() or bom.version  # type: ignore
    bom.output_qty = q3(payload.output_qty)  # type: ignore
    if payload.valid_from and payload.valid_to and payload.valid_from > payload.valid_to:
        raise HTTPException(422, "بداية السريان بعد نهايته")
    bom.is_active = payload.is_active
    bom.valid_from = payload.valid_from
    bom.valid_to = payload.valid_to  # type: ignore
    bom.notes = payload.notes  # type: ignore
    bom.items.clear()
    bom.operations.clear()
    db.flush()
    for item in payload.items:
        db.add(models.BomItem(
            company_id=bom.company_id,  # type: ignore
            bom_id=bom.id,  # type: ignore
            component_id=item.component_id,  # type: ignore
            qty_per_output=item.qty_per_output,  # type: ignore
            scrap_pct=item.scrap_pct,  # type: ignore
            operation_seq=item.operation_seq,  # type: ignore
            notes=item.notes,  # type: ignore
        ))
    for op in payload.operations:
        db.add(models.BomOperation(
            company_id=bom.company_id,  # type: ignore
            bom_id=bom.id,  # type: ignore
            seq=op.seq,
            name=op.name.strip(),
            work_center_id=op.work_center_id,
            run_minutes_per_unit=q3(op.run_minutes_per_unit),  # type: ignore
            notes=op.notes,
        ))
    audit(db, user, "update", "bom", bom, f"{product.name} · {bom.version} · {len(payload.items)} مكوّن · {len(payload.operations)} مرحلة")
    db.commit()
    db.refresh(bom)
    return _bom_out(db, bom)


@boms.delete("/{bom_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bom(bom_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    bom = db.get(models.Bom, bom_id)
    if bom is None or bom.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"BOM {bom_id} not found")
    used = db.query(models.ProductionOrder).filter(models.ProductionOrder.bom_id == bom_id).count()
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, "لا يمكن حذف القائمة — مستخدمة في أوامر تصنيع")
    audit(db, user, "delete", "bom", bom, f"{bom.version}")
    db.delete(bom)
    db.commit()
    return None


# ---------------------------------------------------------------- Work centers (مراكز التشغيل)
@work_centers.get("", response_model=List[schemas.WorkCenterOut])
def list_work_centers(
    active_only: bool = False,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.WorkCenter).filter(models.WorkCenter.company_id == db.info["company_id"])
    if active_only:
        q = q.filter(models.WorkCenter.is_active.is_(True))
    return q.order_by(models.WorkCenter.id).all()


@work_centers.post("", response_model=schemas.WorkCenterOut, status_code=status.HTTP_201_CREATED)
def create_work_center(payload: schemas.WorkCenterIn, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    company_id = db.info["company_id"]
    name = payload.name.strip()
    existing = db.query(models.WorkCenter).filter(models.WorkCenter.company_id == company_id, models.WorkCenter.name == name).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "مركز تشغيل بنفس الاسم موجود بالفعل")
    wc = models.WorkCenter(
        company_id=company_id,  # type: ignore
        name=name,  # type: ignore
        capacity_per_hour=q3(payload.capacity_per_hour) if payload.capacity_per_hour is not None else None,
        hourly_cost=payload.hourly_cost,
        notes=payload.notes,
    )
    db.add(wc)
    db.commit()
    db.refresh(wc)
    audit(db, user, "create", "work_center", wc, name)
    return wc


@work_centers.patch("/{wc_id}", response_model=schemas.WorkCenterOut)
def update_work_center(wc_id: int, payload: schemas.WorkCenterIn, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    wc = db.get(models.WorkCenter, wc_id)
    if wc is None or wc.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Work center {wc_id} not found")
    name = payload.name.strip()
    dup = db.query(models.WorkCenter).filter(models.WorkCenter.company_id == wc.company_id, models.WorkCenter.name == name, models.WorkCenter.id != wc.id).first()
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT, "مركز تشغيل بنفس الاسم موجود بالفعل")
    wc.name = name  # type: ignore
    wc.capacity_per_hour = q3(payload.capacity_per_hour) if payload.capacity_per_hour is not None else None
    wc.hourly_cost = payload.hourly_cost
    wc.notes = payload.notes
    audit(db, user, "update", "work_center", wc, name)
    db.commit()
    db.refresh(wc)
    return wc


@work_centers.delete("/{wc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_work_center(wc_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    wc = db.get(models.WorkCenter, wc_id)
    if wc is None or wc.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Work center {wc_id} not found")
    used_ops = db.query(models.BomOperation).filter(models.BomOperation.work_center_id == wc_id).count()
    used_order_ops = db.query(models.ProductionOrderOperation).filter(models.ProductionOrderOperation.work_center_id == wc_id).count()
    if used_ops or used_order_ops:
        raise HTTPException(status.HTTP_409_CONFLICT, "لا يمكن حذف مركز التشغيل — مرتبط بعمليات في مسارات أو أوامر")
    audit(db, user, "delete", "work_center", wc, wc.name)
    db.delete(wc)
    db.commit()
    return None


# ---------------------------------------------------------------- Production orders
@production_orders.get("", response_model=List[schemas.ProductionOrderOut])
def list_production_orders(
    response: Response,
    product_id: Optional[int] = None,
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(draft|in_progress|completed|cancelled)$"),
    search: Optional[str] = Query(None, max_length=100, description="بحث برقم الأمر أو اسم المنتج"),
    scheduled: Optional[bool] = Query(None, description="حسب وجود تاريخ جدولة — true: مجدولة، false: غير مجدولة"),
    scheduled_from: Optional[date] = Query(None, description="جدولة من تاريخ"),
    scheduled_to: Optional[date] = Query(None, description="جدولة إلى تاريخ"),
    line_id: Optional[int] = Query(None, description="خط إنتاج محدد"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.ProductionOrder).filter(models.ProductionOrder.company_id == db.info["company_id"])
    if product_id is not None:
        q = q.filter(models.ProductionOrder.product_id == product_id)
    if status_filter:
        q = q.filter(models.ProductionOrder.status == status_filter)
    if scheduled is True:
        q = q.filter(models.ProductionOrder.scheduled_date.isnot(None))
    elif scheduled is False:
        q = q.filter(models.ProductionOrder.scheduled_date.is_(None))
    if scheduled_from is not None:
        q = q.filter(models.ProductionOrder.scheduled_date >= scheduled_from)
    if scheduled_to is not None:
        q = q.filter(models.ProductionOrder.scheduled_date <= scheduled_to)
    if line_id is not None:
        q = q.filter(models.ProductionOrder.production_line_id == line_id)
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.outerjoin(models.Product, models.ProductionOrder.product_id == models.Product.id).filter(
            models.ProductionOrder.code.ilike(term) | models.Product.name.ilike(term)
        )
    rows = paginate(q, response, skip, limit, models.ProductionOrder.id.desc())
    # الدقائق المقدرة لكل أمر (Σ دقائق المراحل × الكمية المخططة) — استعلام واحد بدل N+1.
    ids = [po.id for po in rows]
    minutes_map: dict = {}
    if ids:
        minutes_rows = (
            db.query(
                models.ProductionOrderOperation.order_id,
                func.coalesce(
                    func.sum(models.ProductionOrderOperation.run_minutes_per_unit * models.ProductionOrder.qty_planned), 0
                ).label("total"),
            )
            .join(models.ProductionOrder, models.ProductionOrder.id == models.ProductionOrderOperation.order_id)
            .filter(models.ProductionOrderOperation.order_id.in_(ids))
            .group_by(models.ProductionOrderOperation.order_id)
            .all()
        )
        minutes_map = {oid: float(total or 0) for oid, total in minutes_rows}
    for po in rows:
        po.estimated_minutes = minutes_map.get(po.id, 0.0)  # type: ignore[attr-defined]

    # توفر الخامات للأوامر غير المكتملة — دفعتا استعلام بدل استدعاء لكل أمر (نفس دلالات فحص التوفر الفردي).
    pending = [po for po in rows if po.status in ("draft", "in_progress")]
    pending_ids = [po.id for po in pending]
    items_by_order: dict = {}
    if pending_ids:
        for it in db.query(models.ProductionOrderItem).filter(models.ProductionOrderItem.order_id.in_(pending_ids)).all():
            items_by_order.setdefault(it.order_id, []).append(it)
    stock_rows = []
    if pending:
        wh_ids = {po.raw_warehouse_id for po in pending}
        prod_ids = {it.component_id for oid in pending_ids for it in items_by_order.get(oid, [])}
        if prod_ids:
            stock_rows = (
                db.query(models.ProductStock)
                .filter(models.ProductStock.warehouse_id.in_(wh_ids), models.ProductStock.product_id.in_(prod_ids))
                .all()
            )
    available_map = {(s.warehouse_id, s.product_id): dec(s.quantity) for s in stock_rows}
    for po in pending:
        ok_all = True
        for it in items_by_order.get(po.id, []):
            required = dec(it.qty_per_output) * (1 + dec(it.scrap_pct) / 100) * dec(po.qty_planned)
            have = available_map.get((po.raw_warehouse_id, it.component_id), Decimal("0"))
            if required > have:
                ok_all = False
                break
        po.materials_available = ok_all  # type: ignore[attr-defined]
    return [_po_full_out(po) for po in rows]


@production_orders.put("/{order_id}/schedule", response_model=schemas.ProductionOrderOut)
def schedule_production_order(
    order_id: int,
    payload: schemas.ProductionScheduleIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """جدولة أمر تصنيع: تاريخ التشغيل + خط الإنتاج — أساس لوحة الجدولة الأسبوعية."""
    po = _locked_po_or_404(db, order_id)
    if po.status in ("completed", "cancelled"):
        raise HTTPException(status.HTTP_409_CONFLICT, "لا يمكن جدولة أمر مكتمل أو ملغى")
    if payload.production_line_id is not None:
        line = db.get(models.ProductionLine, payload.production_line_id)
        if line is None or line.company_id != db.info["company_id"]:
            raise HTTPException(422, "خط الإنتاج غير موجود")
    po.scheduled_date = payload.scheduled_date  # type: ignore
    po.production_line_id = payload.production_line_id  # type: ignore
    audit(
        db, user, "update", "production_schedule", po,
        f"جدولة {po.code}: {payload.scheduled_date.isoformat() if payload.scheduled_date else 'بلا تاريخ'} · خط {payload.production_line_id or '—'}",
    )
    db.commit()
    db.refresh(po)
    _consumptions_out(po)
    return _po_out(po)


@production_orders.post("", response_model=schemas.ProductionOrderOut, status_code=status.HTTP_201_CREATED)
def create_production_order(
    payload: schemas.ProductionOrderCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    company_id = db.info["company_id"]
    product = db.get(models.Product, payload.product_id)
    if product is None or product.company_id != company_id:
        raise HTTPException(422, "المنتج النهائي غير موجود")
    raw_wh = db.get(models.Warehouse, payload.raw_warehouse_id)
    if raw_wh is None or raw_wh.company_id != company_id:
        raise HTTPException(422, "مخزن الخامات غير موجود")
    out_wh = db.get(models.Warehouse, payload.output_warehouse_id)
    if out_wh is None or out_wh.company_id != company_id:
        raise HTTPException(422, "مخزن المنتج التام غير موجود")
    subcontractor = None
    if payload.subcontractor_id is not None:
        subcontractor = db.get(models.Supplier, payload.subcontractor_id)
        if subcontractor is None or subcontractor.company_id != company_id:
            raise HTTPException(422, "مورد التصنيع الخارجي غير موجود")
    if payload.production_line_id is not None:
        line = db.get(models.ProductionLine, payload.production_line_id)
        if line is None or line.company_id != company_id:
            raise HTTPException(422, "خط الإنتاج غير موجود")
    if payload.sales_order_id is not None:
        so = db.get(models.SalesOrder, payload.sales_order_id)
        if so is None or so.company_id != company_id:
            raise HTTPException(422, "أمر البيع المربوط غير موجود")

    bom = _active_bom(db, company_id, payload.product_id)
    if payload.bom_id is not None and payload.bom_id != bom.id:
        raise HTTPException(422, "قائمة المواد المختارة ليست القائمة المفعّلة لهذا المنتج")
    _check_warehouse_access(db, user, payload.raw_warehouse_id, payload.output_warehouse_id)

    code = unique_code(db, models.ProductionOrder, company_id, product.name, "MO", max_length=50)
    po = models.ProductionOrder(
        company_id=company_id,  # type: ignore
        code=code,  # type: ignore
        product_id=payload.product_id,  # type: ignore
        bom_id=bom.id,  # type: ignore
        qty_planned=q3(payload.qty_planned),  # type: ignore
        status="draft",  # type: ignore
        raw_warehouse_id=payload.raw_warehouse_id,  # type: ignore
        output_warehouse_id=payload.output_warehouse_id,  # type: ignore
        subcontractor_id=payload.subcontractor_id,  # type: ignore
        production_line_id=payload.production_line_id,  # type: ignore
        sales_order_id=payload.sales_order_id,  # type: ignore
        scheduled_date=payload.scheduled_date,  # type: ignore
        notes=payload.notes,  # type: ignore
        created_by=user.id,  # type: ignore
    )
    db.add(po)
    db.flush()
    _snapshot_operations(db, company_id, po, bom)
    po.std_unit_cost = _snapshot_items(db, company_id, po, bom)  # type: ignore
    db.commit()
    db.refresh(po)
    audit(db, user, "create", "production_order", po, f"{code} · {product.name} · {q3(payload.qty_planned)}")
    return _po_out(po)


@production_orders.get("/{order_id}", response_model=schemas.ProductionOrderOut)
def get_production_order(order_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    po = db.get(models.ProductionOrder, order_id)
    if po is None or po.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Production order {order_id} not found")
    po.batches  # load
    po.children = db.query(models.ProductionOrder).filter(
        models.ProductionOrder.company_id == db.info["company_id"],
        models.ProductionOrder.parent_order_id == po.id,
    ).order_by(models.ProductionOrder.id).all()
    for child in po.children:
        _po_out(child)
    return _po_full_out(po)


@production_orders.get("/reports/summary", response_model=schemas.ManufacturingReportOut)
def manufacturing_report(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """تقرير التصنيع: الأوامر المكتملة في الفترة بتكاليفها الفعلية وانحرافاتها + إجمالي الإنتاج لكل منتج."""
    company_id = db.info["company_id"]
    q = db.query(models.ProductionOrder).filter(
        models.ProductionOrder.company_id == company_id,
        models.ProductionOrder.status == "completed",
    )
    if date_from:
        q = q.filter(models.ProductionOrder.completed_at >= date_from)
    if date_to:
        # completed_at يمتد لآخر الليلة عند تصفية بيوم واحد
        q = q.filter(models.ProductionOrder.completed_at < date_to + timedelta(days=1))
    rows = q.order_by(models.ProductionOrder.completed_at).all()

    lines = []
    total_materials = Decimal("0")
    total_costs = Decimal("0")
    total = Decimal("0")
    total_variance = Decimal("0")
    total_variance_std = Decimal("0")
    total_qty = 0
    by_product: dict = {}
    for po in rows:
        materials = _materials_cost(po)
        costs = _costs_total(po)
        total_o = materials + costs
        planned = dec(po.qty_planned)
        unit_cost = (total_o / planned) if planned else Decimal("0")
        # الانحراف المُرحَّل فعليًا = رصيد WIP المتبقي (متسق مع قيود الإغلاق — يشمل الهالك)
        variance = _wip_residual(db, po)
        std_unit = dec(po.std_unit_cost) if po.std_unit_cost is not None else None
        std_total = (std_unit * dec(po.qty_produced)).quantize(Decimal("0.01")) if std_unit is not None else None
        variance_std = (total_o - std_total).quantize(Decimal("0.01")) if std_total is not None else None
        if variance_std is not None:
            total_variance_std += variance_std
        total_materials += materials
        total_costs += costs
        total += total_o
        total_variance += variance
        total_qty = dec(total_qty) + dec(po.qty_produced)
        key = po.product_id
        entry = by_product.setdefault(key, {
            "product_id": po.product_id, "product_name": po.product.name if po.product else None,
            "orders": 0, "qty_produced": Decimal("0"), "total": Decimal("0"),
        })
        entry["orders"] += 1
        entry["qty_produced"] = dec(entry["qty_produced"]) + dec(po.qty_produced)
        entry["total"] += total_o
        lines.append(schemas.ManufacturingReportLine(
            order_id=po.id, code=po.code,
            product_name=po.product.name if po.product else None,
            qty_planned=float(po.qty_planned), qty_produced=float(po.qty_produced or 0),
            materials=materials, costs=costs, total=total_o, unit_cost=unit_cost, variance=variance,
            std_unit_cost=std_unit, std_total=std_total, variance_std=variance_std,
        ))
    by_product_list = [
        schemas.ManufacturingByProduct(**v) for _, v in sorted(by_product.items())
    ]
    return schemas.ManufacturingReportOut(
        date_from=date_from, date_to=date_to,
        lines=lines, total_orders=len(rows), total_qty_produced=float(total_qty),
        total_materials=total_materials, total_costs=total_costs,
        total=total, total_variance=total_variance, total_variance_std=total_variance_std,
        by_product=by_product_list,
    )


def _requirements_for(db: Session, po: models.ProductionOrder, only_seq: Optional[int] = None):
    """احسب متطلبات الصرف من نسخة البنود المثبتة على الأمر (snapshot) — أو من القائمة نفسها للأوامر القديمة.

    (الكمية لكل وحدة × (1 + الفاقد)) × المخطط / كمية الناتج — عشري دقيق.
    only_seq: صرف مكوّنات مرحلة محددة فقط (الصرف المرحلي)؛ None = الصرف المجمّع التقليدي
    (يتخطى المكوّنات المرتبطة بمراحل — تلك تُصرف من endpoint المرحلة). المكوّن الذي له قائمة
    مواد مفعّلة يُستثنى دائمًا (يُنتج عبر أمر تصنيع فرعي).
    """
    bom = po.bom
    if bom is None:
        raise HTTPException(422, "أمر التصنيع بدون قائمة مواد")
    # الأوامر التي أُنشئت قبل الـ snapshot تعود لبنود القائمة مباشرة
    items = list(po.item_snapshots) if po.item_snapshots else list(bom.items)
    output_qty = max(dec(bom.output_qty), Decimal("1"))
    requirements = []
    total_cost = Decimal("0")
    for item in sorted(items, key=lambda it: it.id):
        if item.component_id == po.product_id:
            raise HTTPException(422, "المنتج النهائي لا يمكن أن يكون مكوّنًا في قائمته")
        if only_seq is None and item.operation_seq is not None:
            continue  # مكوّن مرحلي — يُصرف من صرف مرحلته
        if only_seq is not None and item.operation_seq != only_seq:
            continue
        required = q3(dec(item.qty_per_output) * (1 + dec(item.scrap_pct) / 100) * dec(po.qty_planned) / output_qty)
        if required <= 0:
            required = q3("0.001")
        component = db.get(models.Product, item.component_id)
        if component is None or component.company_id != db.info["company_id"]:
            raise HTTPException(422, f"المكوّن {item.component_id} غير موجود")
        unit_cost = dec(component.cost_price)
        has_own_bom = db.query(models.Bom).filter(
            models.Bom.company_id == db.info["company_id"],
            models.Bom.product_id == component.id,
            models.Bom.is_active.is_(True),
        ).first() is not None
        if not has_own_bom:
            total_cost += required * unit_cost
        requirements.append((component, required, unit_cost, has_own_bom))
    return requirements, total_cost


def _allocate_lots(db: Session, company_id: int, warehouse_id: int, product_id: int, qty: Decimal) -> list:
    """تخصيص صرف الخامة من اللوطات FIFO (الأقرب انتهاءً ثم الأقدم أولًا).

    إن لم يكن للخامة أي لوط متبقٍ في المخزن → صرف غير مرتبط بلوط (مخزون قديم قبل تبنّي اللوطات).
    وإن وُجدت لوطات ورصيدها لا يكفي → 409 حتى يُستلم ما يكفي بلوطات.
    """
    lots = (
        db.query(models.StockLot)
        .filter(
            models.StockLot.company_id == company_id,
            models.StockLot.product_id == product_id,
            models.StockLot.warehouse_id == warehouse_id,
            models.StockLot.qty_remaining > 0,
        )
        .order_by(models.StockLot.expiry_date.asc().nullslast(), models.StockLot.created_at.asc(), models.StockLot.id.asc())
        .all()
    )
    if not lots:
        return []
    remaining = Decimal(str(qty))
    allocations: list = []
    for lot in lots:
        if remaining <= 0:
            break
        take = min(Decimal(str(lot.qty_remaining)), remaining)
        lot.qty_remaining = Decimal(str(lot.qty_remaining)) - take  # type: ignore
        allocations.append((lot.id, take))
        remaining -= take
    if remaining > 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"رصيد اللوطات لا يكفي للمكوّن #{product_id} — المتاح باللوطات {qty - remaining} والمطلوب {qty}",
        )
    return allocations


def _issue_requirements(db: Session, po: models.ProductionOrder, requirements, wip_acc: int, inventory_acc: int, user: models.User, label: str):
    """صرف المتطلبات من المخزن (أقفال المنتجات بترتيب ثابت لمنع deadlock) + سطور الاستهلاك + قيد WIP."""
    company_id = db.info["company_id"]
    movable = [(component, required, unit_cost) for component, required, unit_cost, has_own_bom in requirements if not has_own_bom]
    locked: dict = {}
    for pid in sorted({c.id for c, _r, _u in movable}):
        row = db.query(models.Product).filter(models.Product.id == pid).with_for_update().first()
        if row is None:
            raise HTTPException(422, f"المكوّن {pid} غير موجود")
        locked[pid] = row
    # صرف كل الخامات مرة واحدة (all-or-nothing): move_stock يرفع 409 عند نقص أي خامة
    for component, required, _unit_cost in movable:
        move_stock(db, locked[component.id], po.raw_warehouse_id, -required, "production_issue", reference=po.code)
    for component, required, unit_cost in movable:
        db.add(models.ProductionConsumption(
            company_id=company_id,  # type: ignore
            order_id=po.id,  # type: ignore
            component_id=component.id,  # type: ignore
            qty=required,  # type: ignore
            unit_cost=unit_cost,  # type: ignore
        ))
    # تخصيص اللوطات FIFO — يوثّق أي لوط استُهلك لأي مكوّن (التتبع العكسي)
    for component, required, _unit_cost in movable:
        for lot_id, lot_qty in _allocate_lots(db, company_id, po.raw_warehouse_id, component.id, required):
            db.add(models.ConsumptionLot(
                company_id=company_id,  # type: ignore
                order_id=po.id,  # type: ignore
                component_id=component.id,  # type: ignore
                lot_id=lot_id,  # type: ignore
                qty=lot_qty,  # type: ignore
            ))
    total_cost = sum((required * unit_cost for _c, required, unit_cost in movable), Decimal("0"))
    if total_cost > 0:
        AccountingEngine.create_entry(
            db=db,
            company_id=company_id,
            user_id=user.id,
            description=f"Production Order {po.code}: صرف خامات{label}",
            items=[
                {"account_id": wip_acc, "debit": total_cost, "credit": 0},
                {"account_id": inventory_acc, "debit": 0, "credit": total_cost},
            ],
            reference=po.code,
        )
    return total_cost


@production_orders.post("/{order_id}/issue", response_model=schemas.ProductionOrderOut)
def issue_production_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """بدء التشغيل: صرف المكوّنات غير المرتبطة بمراحل (المجمّعة) + قيد WIP + تفعيل المراحل التي لا تستهلك خامات."""
    po = _locked_po_or_404(db, order_id)
    if po.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "الصرف متاح فقط لأوامر التصنيع في حالة مسودة")
    _check_warehouse_access(db, user, po.raw_warehouse_id, po.output_warehouse_id)

    company_id = db.info["company_id"]
    bom = po.bom
    if bom is None or not bom.items:
        raise HTTPException(422, "أمر التصنيع بدون قائمة مواد")
    wip_acc = _account_id_by_code(db, company_id, WIP_CODE)
    inventory_acc = _account_id_by_code(db, company_id, INVENTORY_CODE)

    # مكوّنات بلا مرحلة = الصرف المجمّع التقليدي؛ المرتبطة بمراحل تُصرف من endpoint المرحلة
    requirements, _total = _requirements_for(db, po, only_seq=None)
    snapshot_items = list(po.item_snapshots) if po.item_snapshots else list(bom.items)
    staged_seqs = {it.operation_seq for it in snapshot_items if it.operation_seq is not None}

    total_cost = _issue_requirements(db, po, requirements, wip_acc, inventory_acc, user, label="")

    po.status = "in_progress"  # type: ignore
    for op in po.operations:
        # المرحلة التي لا تستهلك خامات تُصبح جاهزة فورًا؛ التي تستهلك تبقى بانتظار صرفها
        if op.seq not in staged_seqs and op.status == "pending":
            op.status = "in_progress"  # type: ignore

    # التصنيع المرحلي: مكوّن له قائمة مواد مفعّلة -> أنشئ له أمر تصنيع فرعي (مسودة) بنفس الكمية المطلوبة
    children_created = []
    for component, required, _unit_cost, has_own_bom in requirements:
        if not has_own_bom:
            continue
        child_bom = db.query(models.Bom).filter(
            models.Bom.company_id == company_id,
            models.Bom.product_id == component.id,
            models.Bom.is_active.is_(True),
        ).first()
        child_code = unique_code(db, models.ProductionOrder, company_id, component.name, "MO", max_length=50)
        child = models.ProductionOrder(
            company_id=company_id,  # type: ignore
            code=child_code,  # type: ignore
            product_id=component.id,  # type: ignore
            bom_id=child_bom.id,  # type: ignore
            qty_planned=required,  # type: ignore
            status="draft",  # type: ignore
            raw_warehouse_id=po.raw_warehouse_id,  # type: ignore
            output_warehouse_id=po.raw_warehouse_id,  # type: ignore
            parent_order_id=po.id,  # type: ignore
            notes=f"أمر فرعي تلقائي من {po.code} — تشغيلة مكوّن {component.name}",  # type: ignore
            created_by=user.id,  # type: ignore
        )
        db.add(child)
        db.flush()
        _snapshot_operations(db, company_id, child, child_bom)
        children_created.append(child.code)
        audit(db, user, "create", "production_order", child, f"أمر فرعي تلقائي من {po.code} — {component.name} × {q3(required)}")

    audit(db, user, "update", "production_order", po, f"بدء تشغيل {po.code} — صرف خامات {q3(total_cost)}" + (f" · أوامر فرعية: {', '.join(children_created)}" if children_created else ""))
    db.commit()
    db.refresh(po)
    _consumptions_out(po)
    return _po_out(po)


@production_orders.post("/{order_id}/operations/{seq}/issue", response_model=schemas.ProductionOrderOut)
def issue_operation_materials(
    order_id: int,
    seq: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """الصرف المرحلي: صرف خامات مكوّنات مرحلة محددة من مسار التشغيل (قيد WIP مستقل)."""
    po = _locked_po_or_404(db, order_id)
    if po.status != "in_progress":
        raise HTTPException(status.HTTP_409_CONFLICT, "الصرف المرحلي متاح لأوامر قيد التنفيذ فقط")
    _check_warehouse_access(db, user, po.raw_warehouse_id)
    op = next((o for o in po.operations if o.seq == seq), None)
    if op is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"المرحلة {seq} غير موجودة في هذا الأمر")
    if op.issued:
        raise HTTPException(status.HTTP_409_CONFLICT, "خامات هذه المرحلة مصروفة بالفعل")

    company_id = db.info["company_id"]
    bom = po.bom
    if bom is None:
        raise HTTPException(422, "أمر التصنيع بدون قائمة مواد")
    wip_acc = _account_id_by_code(db, company_id, WIP_CODE)
    inventory_acc = _account_id_by_code(db, company_id, INVENTORY_CODE)

    requirements, _total = _requirements_for(db, po, only_seq=seq)
    if not any(not has_own_bom for _c, _r, _u, has_own_bom in requirements):
        raise HTTPException(422, "لا توجد خامات مرتبطة بهذه المرحلة في قائمة المواد")

    total_cost = _issue_requirements(db, po, requirements, wip_acc, inventory_acc, user, label=f" — مرحلة {op.name}")
    op.issued = True  # type: ignore
    if op.status == "pending":
        op.status = "in_progress"  # type: ignore
    audit(db, user, "update", "production_order", po, f"صرف مرحلة {op.name} من {po.code} — {q3(total_cost)}")
    db.commit()
    db.refresh(po)
    _consumptions_out(po)
    return _po_out(po)


@production_orders.post("/{order_id}/operations/{seq}/progress", response_model=schemas.ProductionOrderOut)
def operation_progress(
    order_id: int,
    seq: int,
    payload: schemas.OperationProgressIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """تسجيل تقدم مرحلة: مكتمل + هالك. المرحلة تكتمل عند done+scrapped >= الكمية المخططة.

    إن كانت المرحلة مرتبطة بمركز تشغيل له تكلفة ساعة ووقت تشغيل للوحدة، تُحمَّل أجور
    التشغيل تلقائيًا على الأمر (دقائق × qty_done × تكلفة الساعة / 60) كعبء غير مباشر.
    """
    po = _locked_po_or_404(db, order_id)
    if po.status != "in_progress":
        raise HTTPException(status.HTTP_409_CONFLICT, "تسجيل التقدم متاح لأوامر قيد التنفيذ فقط")
    _check_warehouse_access(db, user, po.raw_warehouse_id, po.output_warehouse_id)
    op = next((o for o in po.operations if o.seq == seq), None)
    if op is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"المرحلة {seq} غير موجودة في هذا الأمر")
    if op.status == "done":
        raise HTTPException(status.HTTP_409_CONFLICT, "المرحلة مكتملة بالفعل")

    qty_done = q3(payload.qty_done)
    qty_scrapped = q3(payload.qty_scrapped)
    if qty_scrapped < 0:
        raise HTTPException(422, "كمية الهالك لا تكون سالبة")
    planned = dec(po.qty_planned)
    already_done = dec(op.qty_done) + dec(op.qty_scrapped)
    if already_done + qty_done + qty_scrapped > planned:
        raise HTTPException(422, f"الإجمالي يتجاوز الكمية المخططة للمرحلة ({q3(planned)})")

    # هالك المرحلة يُرحّل فورًا من WIP إلى مصروف الهالك على أساس متوسط تكلفة الوحدة
    company_id = db.info["company_id"]
    if qty_scrapped > 0:
        total_cost = _total_cost(po)
        unit_cost = (total_cost / planned) if planned else Decimal("0")
        scrap_cost = (unit_cost * qty_scrapped).quantize(Decimal("0.01"))
        if scrap_cost > 0:
            scrap_acc = _account_id_by_code(db, company_id, SCRAP_CODE)
            AccountingEngine.create_entry(
                db=db,
                company_id=company_id,
                user_id=user.id,
                description=f"Production Order {po.code}: هالك مرحلة {op.name} ({q3(qty_scrapped)})",
                items=[
                    {"account_id": scrap_acc, "debit": scrap_cost, "credit": 0},
                    {"account_id": _account_id_by_code(db, company_id, WIP_CODE), "debit": 0, "credit": scrap_cost},
                ],
                reference=po.code,
            )
        po.scrap_cost = dec(po.scrap_cost) + scrap_cost  # type: ignore

    # أجور تشغيل تلقائية من مركز العمل: (دقائق التشغيل للوحدة × الكمية) × تكلفة الساعة / 60
    auto_cost = None
    if qty_done > 0 and op.work_center_id is not None:
        wc = db.get(models.WorkCenter, op.work_center_id)
        hourly = dec(wc.hourly_cost) if wc and wc.hourly_cost is not None else Decimal("0")
        minutes = dec(op.run_minutes_per_unit or 0) * qty_done
        if hourly > 0 and minutes > 0:
            auto_cost = (hourly * minutes / 60).quantize(Decimal("0.01"))
            if auto_cost > 0:
                wip_acc = _account_id_by_code(db, company_id, WIP_CODE)
                overhead_acc = _account_id_by_code(db, company_id, COST_ACCOUNT["overhead"])
                db.add(models.ProductionCost(
                    company_id=company_id,  # type: ignore
                    order_id=po.id,  # type: ignore
                    cost_type="overhead",  # type: ignore
                    amount=auto_cost,  # type: ignore
                    description=f"تشغيل تلقائي — {op.name} ({wc.name}): {q3(minutes)} دقيقة × {hourly}/ساعة",  # type: ignore
                    created_by=user.id,  # type: ignore
                ))
                AccountingEngine.create_entry(
                    db=db,
                    company_id=company_id,
                    user_id=user.id,
                    description=f"Production Order {po.code}: تشغيل {op.name} — {wc.name}",
                    items=[
                        {"account_id": wip_acc, "debit": auto_cost, "credit": 0},
                        {"account_id": overhead_acc, "debit": 0, "credit": auto_cost},
                    ],
                    reference=po.code,
                )

    op.qty_done = dec(op.qty_done) + qty_done  # type: ignore
    op.qty_scrapped = dec(op.qty_scrapped) + qty_scrapped  # type: ignore
    if dec(op.qty_done) + dec(op.qty_scrapped) >= planned:
        op.status = "done"  # type: ignore
        op.completed_at = datetime.now(timezone.utc)  # type: ignore
    elif op.status == "pending":
        op.status = "in_progress"  # type: ignore

    # كل المراحل اكتملت؟ لا نغلق الأمر تلقائيًا — الإنتاج النهائي يبقى عبر produce/close
    audit(db, user, "update", "production_order", po,
          f"تقدم مرحلة {op.name} من {po.code} — مكتمل {q3(qty_done)} · هالك {q3(qty_scrapped)}"
          + (f" · أجور تشغيل تلقائية {auto_cost}" if auto_cost else ""))
    db.commit()
    db.refresh(po)
    _consumptions_out(po)
    return _po_out(po)


@production_orders.post("/{order_id}/produce", response_model=schemas.ProductionOrderOut)
def produce_batch(
    order_id: int,
    payload: schemas.ProductionProduceIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """تسجيل إنتاج دفعة: إضافة الكمية لمخزن المنتج التام + تحديث تكلفة المنتج (متوسط مرجح) + قيد."""
    po = _locked_po_or_404(db, order_id)
    if po.status != "in_progress":
        raise HTTPException(status.HTTP_409_CONFLICT, "الإنتاج متاح فقط لأوامر قيد التنفيذ")
    _check_warehouse_access(db, user, po.output_warehouse_id)
    qty = q3(payload.qty)
    remaining = dec(po.qty_planned) - dec(po.qty_produced) - dec(po.qty_scrapped)
    if qty > remaining:
        raise HTTPException(422, f"الكمية المطلوبة أكبر من المتبقي للتشغيل ({q3(remaining)})")

    company_id = db.info["company_id"]
    wip_acc = _account_id_by_code(db, company_id, WIP_CODE)
    inventory_acc = _account_id_by_code(db, company_id, INVENTORY_CODE)

    # قفل صف المنتج قبل تحريك المخزون (عقد move_stock) — يمنع سباق التكلفة والمخزون
    product = db.query(models.Product).filter(models.Product.id == po.product_id).with_for_update().first()
    if product is None:
        raise HTTPException(422, "المنتج النهائي غير موجود")
    # تكلفة الوحدة المخصصة = إجمالي (الخامات + الأجور والأعباء) / الكمية المخططة
    total_cost = _total_cost(po)
    planned = dec(po.qty_planned)
    unit_cost = (total_cost / planned) if planned else Decimal("0")
    batch_cost = (unit_cost * qty).quantize(Decimal("0.01"))

    # متوسط مرجح لتكلفة المنتج
    old_qty = dec(product.quantity)
    old_cost = dec(product.cost_price)
    new_total_qty = old_qty + qty
    if new_total_qty > 0:
        product.cost_price = ((old_qty * old_cost + batch_cost) / new_total_qty).quantize(Decimal("0.01"))  # type: ignore

    move_stock(db, product, po.output_warehouse_id, qty, "production_receive", reference=po.code)

    if batch_cost > 0:
        AccountingEngine.create_entry(
            db=db,
            company_id=company_id,
            user_id=user.id,
            description=f"Production Order {po.code}: إنتاج {q3(qty)}",
            items=[
                {"account_id": inventory_acc, "debit": batch_cost, "credit": 0},
                {"account_id": wip_acc, "debit": 0, "credit": batch_cost},
            ],
            reference=po.code,
        )

    po.qty_produced = dec(po.qty_produced) + qty  # type: ignore
    batch_seq = db.query(models.ProductionBatch).filter(models.ProductionBatch.order_id == po.id).count() + 1
    try:
        batch_no = f"{po.code}-B{batch_seq}"
        db.add(models.ProductionBatch(
            company_id=company_id,  # type: ignore
            order_id=po.id,  # type: ignore
            batch_no=batch_no,  # type: ignore
            qty=qty,  # type: ignore
            cost=batch_cost,  # type: ignore
        ))
        db.flush()
        # لوط المنتج النهائي بنفس رقم الدفعة: تتبع كامل + بوابة فحص الجودة عند البيع
        lot = (
            db.query(models.StockLot)
            .filter(
                models.StockLot.company_id == company_id,
                models.StockLot.product_id == po.product_id,
                models.StockLot.warehouse_id == po.output_warehouse_id,
                models.StockLot.lot_code == batch_no,
            )
            .first()
        )
        if lot is None:
            db.add(models.StockLot(
                company_id=company_id,  # type: ignore
                product_id=po.product_id,  # type: ignore
                warehouse_id=po.output_warehouse_id,  # type: ignore
                lot_code=batch_no,  # type: ignore
                source="production",  # type: ignore
                reference=po.code,  # type: ignore
                qty_received=q3(qty),  # type: ignore
                qty_remaining=q3(qty),  # type: ignore
            ))
        else:
            lot.qty_remaining = Decimal(str(lot.qty_remaining or 0)) + q3(qty)  # type: ignore
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "تسجيل الإنتاج مكرر — أعد المحاولة")
    if dec(po.qty_produced) + dec(po.qty_scrapped) >= planned:  # type: ignore
        po.status = "completed"  # type: ignore
        po.completed_at = datetime.now(timezone.utc)  # type: ignore
        # اكتمل الأمر: صفِّر WIP تمامًا — أي رصيد متبقٍ (تكاليف أُضيفت بين الدفعات، فواصل تقريب)
        # يُرحَّل لفروق التصنيع. بدون هذا القيد كان WIP يعلق فيه رصيد للأبد.
        residual = _wip_residual(db, po)
        if residual != 0:
            _post_variance(db, po, user, residual, f"Production Order {po.code}: فروق تصنيع (اكتمال تلقائي)")
    audit(db, user, "update", "production_order", po, f"إنتاج {q3(qty)} من {q3(planned)} — تكلفة الدفعة {batch_cost}")
    db.commit()
    db.refresh(po)
    _consumptions_out(po)
    return _po_out(po)


@production_orders.post("/{order_id}/close", response_model=schemas.ProductionOrderOut)
def close_production_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """إنهاء الأمر قبل إكمال الكمية: فروق التصنيع المتبقية تُرحّل لمصاريف متنوعة."""
    po = _locked_po_or_404(db, order_id)
    if po.status != "in_progress":
        raise HTTPException(status.HTTP_409_CONFLICT, "الإنهاء متاح فقط لأوامر قيد التنفيذ")

    # الفروق = رصيد WIP الفعلي المتبقي (خامات + أجور − دفعات مُرحّلة − هالك مُرحّل)
    # الطريقة القديمة (total − unit×produced) كانت تخصم الهالك مرتين وتُدين WIP برصيد سالب.
    variance = _wip_residual(db, po)
    _post_variance(db, po, user, variance, f"Production Order {po.code}: فروق تصنيع")

    po.status = "completed"  # type: ignore
    po.completed_at = datetime.now(timezone.utc)  # type: ignore
    audit(db, user, "update", "production_order", po, f"إنهاء {po.code} — فروق {variance}")
    db.commit()
    db.refresh(po)
    _consumptions_out(po)
    return _po_out(po)


@production_orders.post("/{order_id}/batches/{batch_id}/qc", response_model=schemas.ProductionOrderOut)
def qc_production_batch(
    order_id: int,
    batch_id: int,
    payload: schemas.BatchQcIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """فحص الجودة: اعتماد الدفعة أو رفضها (الرفض يخصم من مخزن الناتج ويرحّل التكلفة لهالك)."""
    po = _locked_po_or_404(db, order_id)
    batch = db.get(models.ProductionBatch, batch_id)
    if batch is None or batch.order_id != po.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Batch {batch_id} not found")
    if batch.qc_status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "تم الفحص من قبل — الدفعة ليس pending")
    notes = (payload.notes or "").strip()
    # بوابة القياسات (اختيارية، معطلة افتراضياً كـ QC_GATE): الاعتماد يُمنع إن وُجد قياس فاشل
    if payload.result == "passed" and os.getenv("QC_MEASURE_GATE", "").strip().lower() in ("1", "true", "yes", "on"):
        max_attempt = (
            db.query(func.max(models.BatchQcResult.attempt))
            .filter(models.BatchQcResult.batch_id == batch_id)
            .scalar()
        ) or 1
        failed = (
            db.query(models.BatchQcResult)
            .filter(
                models.BatchQcResult.batch_id == batch_id,
                models.BatchQcResult.attempt == max_attempt,
                models.BatchQcResult.pass_fail.is_(False),
            )
            .all()
        )
        if failed:
            names = "، ".join(sorted({f.parameter_name for f in failed}))
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"بوابة القياسات: اعتماد الدفعة ممنوع — قياسات غير مطابقة: {names}",
            )
    if payload.result == "rejected" and not notes:
        raise HTTPException(422, "سبب الرفض مطلوب عند رفض الدفعة")

    if payload.result == "rejected":
        product = db.query(models.Product).filter(models.Product.id == po.product_id).with_for_update().first()
        if product is None:
            raise HTTPException(422, "المنتج النهائي غير موجود")
        move_stock(db, product, po.output_warehouse_id, -dec(batch.qty), "production_reject", reference=batch.batch_no)
        # اشطب لوط الدفعة نفسه — بدونه يظل رصيد اللوط أعلى من المخزون الفعلي (انجراف)
        batch_lot = (
            db.query(models.StockLot)
            .filter(
                models.StockLot.company_id == db.info["company_id"],
                models.StockLot.product_id == po.product_id,
                models.StockLot.warehouse_id == po.output_warehouse_id,
                models.StockLot.lot_code == batch.batch_no,
            )
            .first()
        )
        if batch_lot is not None:
            batch_lot.qty_remaining = max(Decimal("0"), Decimal(str(batch_lot.qty_remaining or 0)) - dec(batch.qty))  # type: ignore
        company_id = db.info["company_id"]
        inventory_acc = _account_id_by_code(db, company_id, INVENTORY_CODE)
        scrap_acc = _account_id_by_code(db, company_id, SCRAP_CODE)
        AccountingEngine.create_entry(
            db=db,
            company_id=company_id,
            user_id=user.id,
            description=f"Production Order {po.code}: رفض فحص الدفعة {batch.batch_no}",
            items=[
                {"account_id": scrap_acc, "debit": batch.cost, "credit": 0},
                {"account_id": inventory_acc, "debit": 0, "credit": batch.cost},
            ],
            reference=batch.batch_no,
        )
        # أنزِل متوسط تكلفة المنتج المرجّح — الدفعة المرفوضة خرجت من المخزون فلا تظل رافعة المتوسط
        old_qty = dec(product.quantity)  # بعد خصم الدفعة (move_stock حدّث الرصيد)
        old_cost = dec(product.cost_price)
        if old_qty > 0:
            product.cost_price = ((old_qty * old_cost - dec(batch.cost)) / old_qty).quantize(Decimal("0.01"))  # type: ignore
        else:
            product.cost_price = dec("0")  # type: ignore
    batch.qc_status = payload.result  # type: ignore
    batch.notes = notes or None  # type: ignore
    audit(db, user, "update", "production_batch", batch, f"فحص {batch.batch_no}: {payload.result}" + (f" — {notes}" if notes else ""))
    db.commit()
    db.refresh(po)
    return _po_out(po)


@production_orders.post("/{order_id}/scrape", response_model=schemas.ProductionOrderOut)
def scrape_production_order(
    order_id: int,
    payload: schemas.ProductionScrapIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """تسجيل هالك من أمر قيد التشغيل: الكمية الهالكة تُرحّل من WIP لمصروف هالك."""
    po = _locked_po_or_404(db, order_id)
    if po.status != "in_progress":
        raise HTTPException(status.HTTP_409_CONFLICT, "الهالك متاح فقط لأوامر قيد التنفيذ")
    _check_warehouse_access(db, user, po.raw_warehouse_id, po.output_warehouse_id)
    qty = q3(payload.qty)
    remaining_planned = dec(po.qty_planned) - dec(po.qty_produced) - dec(po.qty_scrapped)
    if qty > remaining_planned:
        raise HTTPException(422, f"كمية الهالك أكبر من المتبقي للتشغيل ({q3(remaining_planned)})")

    company_id = db.info["company_id"]
    wip_acc = _account_id_by_code(db, company_id, WIP_CODE)
    scrap_acc = _account_id_by_code(db, company_id, SCRAP_CODE)
    planned = dec(po.qty_planned)
    unit_cost = (_total_cost(po) / planned) if planned else Decimal("0")
    scrap_cost = (unit_cost * qty).quantize(Decimal("0.01"))

    if scrap_cost > 0:
        AccountingEngine.create_entry(
            db=db,
            company_id=company_id,
            user_id=user.id,
            description=f"Production Order {po.code}: هالك {q3(qty)}",
            items=[
                {"account_id": scrap_acc, "debit": scrap_cost, "credit": 0},
                {"account_id": wip_acc, "debit": 0, "credit": scrap_cost},
            ],
            reference=po.code,
        )

    po.qty_scrapped = dec(po.qty_scrapped) + qty  # type: ignore
    po.scrap_cost = dec(po.scrap_cost) + scrap_cost  # type: ignore
    if payload.notes and payload.notes.strip():
        po.notes = ((po.notes or "") + ("\n" if po.notes else "") + f"هالك {q3(qty)}: {payload.notes.strip()}").strip()  # type: ignore
    audit(db, user, "update", "production_order", po, f"هالك {q3(qty)} من {po.code} — {scrap_cost}")
    db.commit()
    db.refresh(po)
    _consumptions_out(po)
    return _po_out(po)


@production_orders.get("/reports/wip", response_model=List[schemas.WipOrderOut])
def wip_report(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """الأوامر قيد التنفيذ: قيمة WIP الحالية والمتبقي للتشغيل."""
    rows = db.query(models.ProductionOrder).filter(
        models.ProductionOrder.company_id == db.info["company_id"],
        models.ProductionOrder.status == "in_progress",
    ).order_by(models.ProductionOrder.id).all()
    out = []
    for po in rows:
        _consumptions_out(po)
        materials = _materials_cost(po)
        costs = _costs_total(po)
        total = materials + costs
        out.append(schemas.WipOrderOut(
            id=po.id, code=po.code,
            product_id=po.product_id,
            product_name=po.product.name if po.product else None,
            qty_planned=float(po.qty_planned), qty_produced=float(po.qty_produced or 0),
            remaining=float(dec(po.qty_planned) - dec(po.qty_produced) - dec(po.qty_scrapped)),
            materials=materials, costs=costs, wip_value=total,
            unit_cost=(total / dec(po.qty_planned)) if po.qty_planned else Decimal("0"),
            scheduled_date=po.scheduled_date,
        ))
    return out


@production_orders.get("/{order_id}/children", response_model=List[schemas.ProductionOrderOut])
def list_child_orders(order_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rows = db.query(models.ProductionOrder).filter(
        models.ProductionOrder.company_id == db.info["company_id"],
        models.ProductionOrder.parent_order_id == order_id,
    ).order_by(models.ProductionOrder.id).all()
    return [_po_out(po) for po in rows]


@production_orders.post("/{order_id}/cancel", response_model=schemas.ProductionOrderOut)
def cancel_production_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    po = _locked_po_or_404(db, order_id)
    if po.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "الإلغاء متاح فقط لأوامر في حالة مسودة (قبل صرف الخامات)")
    po.status = "cancelled"  # type: ignore
    audit(db, user, "update", "production_order", po, f"إلغاء {po.code}")
    db.commit()
    db.refresh(po)
    return _po_out(po)


@production_orders.post("/{order_id}/cancel-running", response_model=schemas.ProductionOrderOut)
def cancel_running_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """إيقاف أمر قيد التنفيذ بالكامل: إرجاع الخامات المصروفة لمخزنها + عكس قيود الأجور — WIP يُصفَّر.

    متاح فقط إذا لم يُنتج أو يُسجَّل هالك بعد (بعد ذلك الطريق الوحيد هو «إنهاء» بترحيل الفروق).
    """
    po = _locked_po_or_404(db, order_id)
    if po.status != "in_progress":
        raise HTTPException(status.HTTP_409_CONFLICT, "الإيقاف متاح لأوامر قيد التنفيذ فقط (للمسودة استخدم الإلغاء العادي)")
    if dec(po.qty_produced) > 0 or po.batches:
        raise HTTPException(status.HTTP_409_CONFLICT, "لا يمكن الإيقاف بعد تسجيل دفعات إنتاج — استخدم «إنهاء» لترحيل الفروق")
    if dec(po.qty_scrapped) > 0 or dec(po.scrap_cost) > 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "لا يمكن الإيقاف بعد تسجيل هالك — استخدم «إنهاء» لترحيل الفروق")
    _check_warehouse_access(db, user, po.raw_warehouse_id, po.output_warehouse_id)

    company_id = db.info["company_id"]
    wip_acc = _account_id_by_code(db, company_id, WIP_CODE)
    inventory_acc = _account_id_by_code(db, company_id, INVENTORY_CODE)

    # 1) إرجاع كل الخامات المصروفة (المجمّعة والمرحلية) إلى مخزن الخامات — بقفل المنتجات
    locked = {}
    for pid in sorted({c.component_id for c in po.consumptions}):
        locked[pid] = db.query(models.Product).filter(models.Product.id == pid).with_for_update().first()
    for c in po.consumptions:
        move_stock(db, locked[c.component_id], po.raw_warehouse_id, dec(c.qty), "production_return", reference=po.code)
    materials_total = _materials_cost(po)
    if materials_total > 0:
        AccountingEngine.create_entry(
            db=db, company_id=company_id, user_id=user.id,
            description=f"Production Order {po.code}: إيقاف وإرجاع خامات",
            items=[
                {"account_id": inventory_acc, "debit": materials_total, "credit": 0},
                {"account_id": wip_acc, "debit": 0, "credit": materials_total},
            ],
            reference=po.code,
        )

    # 2) عكس كل قيود الأجور/الأعباء/الخارجي وحذف سطورها (لم يُنتج شيء فلا تُحمَّل على WIP)
    for cost in list(po.costs):
        if cost.cost_type == "subcontract":
            supplier = db.get(models.Supplier, po.subcontractor_id) if po.subcontractor_id else None
            credit_acc = supplier.chart_account_id if supplier else None
            if credit_acc is None:
                raise HTTPException(422, "لا يمكن عكس قيد التصنيع الخارجي — المورد بلا حساب محاسبي مرتبط")
        else:
            credit_acc = _account_id_by_code(db, company_id, COST_ACCOUNT[cost.cost_type])
        AccountingEngine.create_entry(
            db=db, company_id=company_id, user_id=user.id,
            description=f"Production Order {po.code}: عكس {COST_LABEL[cost.cost_type]} عند الإيقاف",
            items=[
                {"account_id": credit_acc, "debit": dec(cost.amount), "credit": 0},
                {"account_id": wip_acc, "debit": 0, "credit": dec(cost.amount)},
            ],
            reference=po.code,
        )
        db.delete(cost)

    # إعادة اللوطات المستهلكة إلى رصيدها (التتبع يبقى موثقًا بالسجل)
    for cl in db.query(models.ConsumptionLot).filter(models.ConsumptionLot.order_id == po.id).all():
        lot = db.get(models.StockLot, cl.lot_id)
        if lot is not None:
            lot.qty_remaining = Decimal(str(lot.qty_remaining)) + Decimal(str(cl.qty))  # type: ignore
    db.query(models.ConsumptionLot).filter(models.ConsumptionLot.order_id == po.id).delete(synchronize_session=False)

    po.status = "cancelled"  # type: ignore
    po.notes = ((po.notes or "") + ("\n" if po.notes else "") + "أُوقف الأمر وأُرجعت خاماته للمخزن").strip()  # type: ignore
    audit(db, user, "update", "production_order", po, f"إيقاف {po.code} وإرجاع خامات بقيمة {materials_total}")
    db.commit()
    db.refresh(po)
    _consumptions_out(po)
    return _po_out(po)


@production_orders.get("/{order_id}/materials-availability", response_model=schemas.MaterialsAvailabilityOut)
def materials_availability(order_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """فحص قبل بدء التشغيل: المطلوب من كل خامة مقابل المتاح في مخزن الخامات الآن.

    يشمل الخامات المرحلية (تُصرف عند مرحلتها)؛ المكوّنات التي تُنتج بأوامر فرعية مستثناة
    لأنها لا تُصرف من المخزن عند بدء التشغيل.
    """
    po = db.get(models.ProductionOrder, order_id)
    if po is None or po.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Production order {order_id} not found")
    if po.status not in ("draft", "in_progress"):
        raise HTTPException(status.HTTP_409_CONFLICT, "الفحص متاح لأوامر في المسودة أو قيد التنفيذ")

    company_id = db.info["company_id"]
    bom = po.bom
    if bom is None:
        raise HTTPException(422, "أمر التصنيع بدون قائمة مواد")
    items = list(po.item_snapshots) if po.item_snapshots else list(bom.items)
    output_qty = max(dec(bom.output_qty), Decimal("1"))

    lines = []
    missing = 0
    for item in sorted(items, key=lambda it: it.id):
        component = db.get(models.Product, item.component_id)
        if component is None:
            continue
        has_own_bom = db.query(models.Bom).filter(
            models.Bom.company_id == company_id,
            models.Bom.product_id == component.id,
            models.Bom.is_active.is_(True),
        ).first() is not None
        if has_own_bom:
            continue  # يُنتج بأمر فرعي — لا يُصرف من المخزن
        required = q3(dec(item.qty_per_output) * (1 + dec(item.scrap_pct) / 100) * dec(po.qty_planned) / output_qty)
        available_qty = q3(stock_available(db, component.id, po.raw_warehouse_id))
        enough = available_qty >= required
        if not enough:
            missing += 1
        lines.append(schemas.MaterialsAvailabilityItem(
            component_id=component.id, component_name=component.name, component_unit=component.unit,
            required=required, available=available_qty, unit_cost=dec(component.cost_price),
            enough=enough, staged=item.operation_seq is not None,
        ))
    return schemas.MaterialsAvailabilityOut(
        order_id=po.id, code=po.code,
        warehouse_name=po.raw_warehouse.name if po.raw_warehouse else None,
        lines=lines, all_available=missing == 0, missing_count=missing,
    )


@production_orders.get("/batches/trace", response_model=schemas.BatchTraceOut)
def trace_batch(batch_no: str, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """تتبع دفعة للخلف: من أي أمر صُنعت، من أي خامات، ودفعات الأوامر الفرعية المرتبطة بها."""
    batch = (
        db.query(models.ProductionBatch)
        .join(models.ProductionOrder, models.ProductionBatch.order_id == models.ProductionOrder.id)
        .filter(
            models.ProductionOrder.company_id == db.info["company_id"],
            models.ProductionBatch.batch_no == batch_no.strip(),
        )
        .first()
    )
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا توجد دفعة بالرقم {batch_no}")
    po = batch.order
    _consumptions_out(po)
    children = db.query(models.ProductionOrder).filter(
        models.ProductionOrder.company_id == db.info["company_id"],
        models.ProductionOrder.parent_order_id == po.id,
    ).order_by(models.ProductionOrder.id).all()
    return schemas.BatchTraceOut(
        batch_no=batch.batch_no, qty=dec(batch.qty), cost=dec(batch.cost), qc_status=batch.qc_status,
        produced_at=batch.produced_at, order_id=po.id, order_code=po.code, order_status=po.status,
        product_name=po.product.name if po.product else None,
        consumptions=[schemas.ProductionConsumptionOut.model_validate(c) for c in po.consumptions],
        children=[schemas.BatchTraceChild(
            code=c.code,
            product_name=c.product.name if c.product else None,
            batches=[b.batch_no for b in c.batches],
        ) for c in children],
    )


@production_orders.get("/lots/{lot_id}/trace-forward", response_model=schemas.ForwardTraceOut)
def trace_forward_lot(lot_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """تتبع أمامي (سحب استدعاء): لوط خام ← كل أوامر التصنيع التي استهلكته ← دفعاته النهائية ورصيدها الحالي."""
    company_id = db.info["company_id"]
    lot = db.get(models.StockLot, lot_id)
    if lot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"اللوط {lot_id} غير موجود")
    product = db.get(models.Product, lot.product_id)
    consumptions = (
        db.query(models.ConsumptionLot)
        .join(models.ProductionOrder, models.ConsumptionLot.order_id == models.ProductionOrder.id)
        .filter(models.ConsumptionLot.lot_id == lot_id, models.ProductionOrder.company_id == company_id)
        .order_by(models.ConsumptionLot.order_id)
        .all()
    )
    out_orders: List[schemas.ForwardTraceOrder] = []
    for c in consumptions:
        po = c.order
        batches = (
            db.query(models.ProductionBatch)
            .filter(models.ProductionBatch.order_id == po.id)
            .order_by(models.ProductionBatch.id)
            .all()
        )
        out_batches: List[schemas.ForwardTraceBatch] = []
        for b in batches:
            finished_lot = (
                db.query(models.StockLot)
                .filter(
                    models.StockLot.company_id == company_id,
                    models.StockLot.product_id == po.product_id,
                    models.StockLot.lot_code == b.batch_no,
                )
                .with_entities(func.coalesce(func.sum(models.StockLot.qty_remaining), 0))
                .scalar()
            )
            out_batches.append(schemas.ForwardTraceBatch(
                batch_no=b.batch_no, qty=dec(b.qty), qc_status=b.qc_status,
                finished_lot_qty=Decimal(str(finished_lot or 0)),
            ))
        out_orders.append(schemas.ForwardTraceOrder(
            order_id=po.id, order_code=po.code, order_status=po.status,
            product_name=po.product.name if po.product else None,
            consumed_qty=dec(c.qty),
            batches=out_batches,
        ))
    return schemas.ForwardTraceOut(
        lot_id=lot.id,
        lot_code=lot.lot_code,
        product_id=lot.product_id,
        product_name=product.name if product else None,
        orders=out_orders,
    )


@production_orders.get("/reports/work-centers", response_model=schemas.WorkCenterPerfOut)
def work_centers_performance(
    date_from: Optional[date] = Query(None, description="من تاريخ إنشاء الأوامر"),
    date_to: Optional[date] = Query(None, description="إلى تاريخ إنشاء الأوامر"),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """أداء مراكز التشغيل: الدقائق الفعلية (المنجز × دقائق الوحدة) مقابل المخططة — بذرة قياس الكفاءة."""
    company_id = db.info["company_id"]
    q = (
        db.query(
            models.ProductionOrderOperation.work_center_id,
            func.count(func.distinct(models.ProductionOrderOperation.order_id)).label("orders_count"),
            func.coalesce(func.sum(models.ProductionOrderOperation.qty_done), 0).label("qty_done"),
            func.coalesce(func.sum(models.ProductionOrderOperation.qty_scrapped), 0).label("qty_scrapped"),
            func.coalesce(func.sum(models.ProductionOrderOperation.qty_done * models.ProductionOrderOperation.run_minutes_per_unit), 0).label("actual_minutes"),
            func.coalesce(func.sum(models.ProductionOrderOperation.run_minutes_per_unit * models.ProductionOrder.qty_planned), 0).label("planned_minutes"),
        )
        .join(models.ProductionOrder, models.ProductionOrder.id == models.ProductionOrderOperation.order_id)
        .filter(
            models.ProductionOrder.company_id == company_id,
            models.ProductionOrderOperation.work_center_id.isnot(None),
        )
    )
    if date_from is not None:
        q = q.filter(models.ProductionOrder.created_at >= date_from)
    if date_to is not None:
        q = q.filter(models.ProductionOrder.created_at < date_to + timedelta(days=1))
    perf_rows = q.group_by(models.ProductionOrderOperation.work_center_id).all()
    perf = {r.work_center_id: r for r in perf_rows}
    centers = (
        db.query(models.WorkCenter)
        .filter(models.WorkCenter.company_id == company_id)
        .order_by(models.WorkCenter.name)
        .all()
    )
    out = []
    for wc in centers:
        r = perf.get(wc.id)
        actual = float(r.actual_minutes or 0) if r else 0.0
        planned = float(r.planned_minutes or 0) if r else 0.0
        out.append(
            schemas.WorkCenterPerfRow(
                work_center_id=wc.id,
                name=wc.name,
                orders_count=int(r.orders_count or 0) if r else 0,
                qty_done=float(r.qty_done or 0) if r else 0.0,
                qty_scrapped=float(r.qty_scrapped or 0) if r else 0.0,
                actual_minutes=actual,
                planned_minutes=planned,
                utilization=round(actual / planned * 100, 1) if planned > 0 else 0.0,
            )
        )
    return schemas.WorkCenterPerfOut(date_from=date_from, date_to=date_to, rows=out)


@production_orders.get("/{order_id}/lots", response_model=List[schemas.ConsumptionLotRow])
def order_consumption_lots(order_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """التتبع العكسي: اللوطات التي استهلكها أمر التصنيع (من الدفعة إلى طبيب الاستلام)."""
    po = db.get(models.ProductionOrder, order_id)
    if po is None or po.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "أمر التصنيع غير موجود")
    rows = (
        db.query(models.ConsumptionLot, models.StockLot, models.Product)
        .join(models.StockLot, models.StockLot.id == models.ConsumptionLot.lot_id)
        .join(models.Product, models.Product.id == models.ConsumptionLot.component_id)
        .filter(models.ConsumptionLot.order_id == order_id)
        .order_by(models.Product.name.asc(), models.StockLot.lot_code.asc())
        .all()
    )
    return [
        schemas.ConsumptionLotRow(
            component_id=cl.component_id,
            component_name=p.name,
            lot_id=sl.id,
            lot_code=sl.lot_code,
            qty=float(cl.qty or 0),
            source=sl.source,
            reference=sl.reference,
            expiry_date=sl.expiry_date,
        )
        for cl, sl, p in rows
    ]


@production_orders.get("/mrp/suggestions", response_model=schemas.MrpSuggestionOut)
def mrp_suggestions(
    product_id: int,
    qty: float = Query(gt=0),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """اقتراحات تخطيط الاحتياجات: فجّر قائمة المواد عبر كل المستويات وقارن بالمخزون الكلي.

    لكل مكوّن: العجز واقتراح الكمية — إنتاج داخلي (له قائمة مواد) أو شراء.
    """
    company_id = db.info["company_id"]
    product = db.get(models.Product, product_id)
    if product is None or product.company_id != company_id:
        raise HTTPException(422, "المنتج غير موجود")

    totals: dict = {}  # component_id -> Decimal إجمالي المطلوب عبر كل المستويات
    has_bom_cache: dict = {}

    def component_has_bom(pid: int) -> bool:
        if pid not in has_bom_cache:
            has_bom_cache[pid] = _bom_window_query(db, company_id, pid, date.today()).first() is not None
        return has_bom_cache[pid]

    def explode(pid: int, quantity: Decimal, chain: tuple) -> None:
        if len(chain) >= 10:
            raise HTTPException(422, f"تعذر التفكيك — سلسلة قوائم مواد دائرية تشمل المنتج {pid}")
        if pid in chain:
            raise HTTPException(422, "قوائم المواد دائرية (منتج مكوّن في سلسلة نفسه)")
        bom = _bom_window_query(db, company_id, pid, date.today()).first()
        if bom is None:
            return
        output_qty = max(dec(bom.output_qty), Decimal("1"))
        for item in bom.items:
            required = dec(item.qty_per_output) * (1 + dec(item.scrap_pct) / 100) * quantity / output_qty
            totals[item.component_id] = totals.get(item.component_id, Decimal("0")) + required
            if component_has_bom(item.component_id):
                explode(item.component_id, required, chain + (pid,))

    explode(product_id, dec(str(qty)), ())

    lines = []
    for comp_id in sorted(totals):
        comp = db.get(models.Product, comp_id)
        if comp is None:
            continue
        in_stock = dec(comp.quantity)
        shortfall = max(Decimal("0"), (totals[comp_id] - in_stock).quantize(Decimal("0.001")))
        lines.append(schemas.MrpComponentSuggestion(
            product_id=comp_id, product_name=comp.name, unit=comp.unit,
            required_total=totals[comp_id].quantize(Decimal("0.001")),
            in_stock=in_stock, shortfall=shortfall,
            has_bom=component_has_bom(comp_id), suggested_qty=shortfall,
        ))
    return schemas.MrpSuggestionOut(product_id=product_id, product_name=product.name, qty=dec(str(qty)), lines=lines)


@production_orders.get("/mrp/aggregate", response_model=schemas.MrpAggregateOut)
def mrp_aggregate(
    sales_order_id: Optional[int] = Query(None, description="حصر الطلب على أمر بيع واحد (MTO)"),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """تخطيط الاحتياجات الإجمالي: لكل منتج له قائمة مواد مفعّلة — كميات أوامر البيع المسودة
    (الطلب القادم) مقابل الرصيد الكلي، مع اقتراح كمية إنتاج عند العجز.
    مع sales_order_id: النواقص اللازمة لتنفيذ أمر بيع بعينه."""
    company_id = db.info["company_id"]
    if sales_order_id is not None:
        so = db.get(models.SalesOrder, sales_order_id)
        if so is None or so.company_id != company_id:
            raise HTTPException(404, "أمر البيع غير موجود")
    # الطلب المفتوح = بنود أوامر البيع المسودة (المؤكدة خُصم مخزونها بالفعل)
    demand_rows = (
        db.query(models.SalesOrderItem.product_id, func.sum(models.SalesOrderItem.quantity))
        .join(models.SalesOrder, models.SalesOrderItem.order_id == models.SalesOrder.id)
        .filter(models.SalesOrder.company_id == company_id, models.SalesOrder.status == "draft")
        .group_by(models.SalesOrderItem.product_id)
        .all()
    )
    # (لأمر بيع واحد: استعلام مباشر على بنوده بدل مسودة الكل)
    if sales_order_id is not None:
        demand_rows = (
            db.query(models.SalesOrderItem.product_id, func.sum(models.SalesOrderItem.quantity))
            .filter(models.SalesOrderItem.order_id == sales_order_id)
            .group_by(models.SalesOrderItem.product_id)
            .all()
        )
    demand = {pid: dec(qty) for pid, qty in demand_rows}
    lines = []
    for bom in db.query(models.Bom).filter(models.Bom.company_id == company_id, models.Bom.is_active.is_(True)).all():
        product = bom.product
        if product is None or demand.get(product.id, Decimal("0")) <= 0:
            continue
        in_stock = dec(product.quantity)
        open_demand = demand[product.id]
        shortfall = max(Decimal("0"), (open_demand - in_stock).quantize(Decimal("0.001")))
        if shortfall <= 0:
            continue
        lines.append(schemas.MrpAggregateRow(
            product_id=product.id, product_name=product.name, unit=product.unit,
            in_stock=in_stock, open_demand=open_demand, shortfall=shortfall, has_bom=True,
        ))
    lines.sort(key=lambda r: r.shortfall, reverse=True)
    return schemas.MrpAggregateOut(lines=lines)


@production_orders.post("/mrp/execute", response_model=schemas.MrpExecuteOut)
def mrp_execute(
    payload: schemas.MrpExecuteIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """MRP التنفيذي: تحويل اقتراحات التخطيط إلى أوامر فعلية —
    produce → أمر تصنيع مسودة (بقائمة المواد السارية)؛ buy → أمر شراء مسودة للمورد.
    العناصر المتعذرة تُعاد في skipped بسببها ولا يفشل الباقي."""
    company_id = db.info["company_id"]
    raw_wh = db.get(models.Warehouse, payload.raw_warehouse_id)
    if raw_wh is None or raw_wh.company_id != company_id:
        raise HTTPException(422, "مخزن الخامات غير موجود")
    out_wh = db.get(models.Warehouse, payload.output_warehouse_id)
    if out_wh is None or out_wh.company_id != company_id:
        raise HTTPException(422, "مخزن الناتج غير موجود")
    purchase_wh_id = payload.purchase_warehouse_id or payload.raw_warehouse_id
    if payload.purchase_warehouse_id is not None:
        pwh = db.get(models.Warehouse, payload.purchase_warehouse_id)
        if pwh is None or pwh.company_id != company_id:
            raise HTTPException(422, "مخزن استلام الشراء غير موجود")

    created: List[schemas.MrpExecuteResult] = []
    skipped: List[schemas.MrpExecuteResult] = []

    for item in payload.items:
        product = db.get(models.Product, item.product_id)
        if product is None or product.company_id != company_id:
            skipped.append(schemas.MrpExecuteResult(product_id=item.product_id, action=item.action, ok=False, reason="المنتج غير موجود"))
            continue
        if item.action == "produce":
            try:
                bom = _active_bom(db, company_id, item.product_id)
            except HTTPException:
                skipped.append(schemas.MrpExecuteResult(product_id=item.product_id, action=item.action, ok=False, reason="لا قائمة مواد سارية"))
                continue
            code = unique_code(db, models.ProductionOrder, company_id, product.name, "MO", max_length=50)
            mo = models.ProductionOrder(
                company_id=company_id, code=code, product_id=item.product_id, bom_id=bom.id,
                qty_planned=q3(item.qty), status="draft",
                raw_warehouse_id=payload.raw_warehouse_id, output_warehouse_id=payload.output_warehouse_id,
                scheduled_date=item.scheduled_date, created_by=user.id,
            )
            db.add(mo)
            db.flush()
            _snapshot_operations(db, company_id, mo, bom)
            mo.std_unit_cost = _snapshot_items(db, company_id, mo, bom)
            audit(db, user, "create", "production_order", mo, f"MRP execute · {code} · {q3(item.qty)}")
            created.append(schemas.MrpExecuteResult(product_id=item.product_id, action=item.action, ok=True, order_id=mo.id, order_code=code))
        else:  # buy
            if item.supplier_id is None:
                skipped.append(schemas.MrpExecuteResult(product_id=item.product_id, action=item.action, ok=False, reason="المورد مطلوب لأمر الشراء"))
                continue
            supplier = db.get(models.Supplier, item.supplier_id)
            if supplier is None or supplier.company_id != company_id:
                skipped.append(schemas.MrpExecuteResult(product_id=item.product_id, action=item.action, ok=False, reason="المورد غير موجود"))
                continue
            qty = q3(item.qty)
            cost = item.purchase_price if item.purchase_price is not None else dec(product.cost_price)
            porder = models.PurchaseOrder(
                supplier_id=supplier.id, warehouse_id=purchase_wh_id,
                notes="مسودة من MRP التنفيذي", status="draft",
            )
            porder.items.append(models.PurchaseOrderItem(product_id=item.product_id, quantity=qty, unit_cost=cost))
            porder.total_amount = (cost * qty).quantize(Decimal("0.01"))
            db.add(porder)
            db.flush()
            audit(db, user, "create", "purchase_order", porder, f"MRP execute · {product.name} · {qty}")
            created.append(schemas.MrpExecuteResult(product_id=item.product_id, action=item.action, ok=True, order_id=porder.id, order_code=f"PO-{porder.id}"))
    db.commit()
    return schemas.MrpExecuteOut(created=created, skipped=skipped)


@production_orders.get("/{order_id}/print-card", response_class=Response)
def print_production_card(order_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """بطاقة أمر التصنيع للطباعة (HTML بالعربية RTL): بيانات الأمر + الخامات + المراحل + الدفعات."""
    po = db.get(models.ProductionOrder, order_id)
    if po is None or po.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Production order {order_id} not found")
    _consumptions_out(po)
    for op in po.operations:
        op.work_center_name = op.work_center.name if op.work_center else None  # type: ignore[attr-defined]

    def esc(value) -> str:
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    status_label = {"draft": "مسودة", "in_progress": "قيد التنفيذ", "completed": "مكتمل", "cancelled": "ملغي"}.get(po.status, po.status)
    rows_items = ""
    for c in po.consumptions:
        rows_items += f"<tr><td>{esc(c.component_name)}</td><td>{esc(c.component_unit or '—')}</td><td>{q3(c.qty)}</td><td>{dec(c.unit_cost)}</td><td>{dec(c.qty) * dec(c.unit_cost):.2f}</td></tr>"
    if not rows_items:
        rows_items = "<tr><td colspan='5' style='text-align:center;color:#888'>لم يتم صرف خامات بعد</td></tr>"
    rows_ops = ""
    for op in po.operations:
        rows_ops += f"<tr><td>{op.seq}</td><td>{esc(op.name)}</td><td>{esc(op.work_center_name or '—')}</td><td>{q3(op.run_minutes_per_unit)}</td><td>{esc({'pending': 'لم تبدأ', 'in_progress': 'قيد التنفيذ', 'done': 'مكتملة'}.get(op.status, op.status))}</td></tr>"
    if not rows_ops:
        rows_ops = "<tr><td colspan='5' style='text-align:center;color:#888'>لا يوجد مسار تشغيل</td></tr>"
    rows_batches = ""
    for b in po.batches:
        qc = {"pending": "قيد الفحص", "passed": "معتمدة", "rejected": "مرفوضة"}.get(b.qc_status, b.qc_status)
        rows_batches += f"<tr><td>{esc(b.batch_no)}</td><td>{q3(b.qty)}</td><td>{dec(b.cost):.2f}</td><td>{esc(qc)}</td></tr>"
    if not rows_batches:
        rows_batches = "<tr><td colspan='4' style='text-align:center;color:#888'>لا توجد دفعات</td></tr>"

    html = f"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<title>بطاقة أمر تصنيع {esc(po.code)}</title>
<style>
body{{font-family:'Segoe UI',Tahoma,sans-serif;margin:24px;color:#111}}
h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:15px;margin:18px 0 6px;border-bottom:2px solid #2563eb;padding-bottom:3px}}
.meta{{display:flex;gap:18px;flex-wrap:wrap;font-size:13px;background:#f1f5f9;padding:10px;border-radius:8px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{border:1px solid #cbd5e1;padding:6px 8px;text-align:right}}
th{{background:#e2e8f0}}
.totals{{margin-top:14px;font-size:14px;display:flex;gap:20px;flex-wrap:wrap;background:#f8fafc;padding:10px;border-radius:8px;border:1px solid #e2e8f0}}
@media print{{body{{margin:8px}}}}
</style></head><body>
<h1>بطاقة أمر تصنيع — {esc(po.code)}</h1>
<div class="meta">
<span><b>المنتج:</b> {esc(po.product.name if po.product else '')}</span>
<span><b>الحالة:</b> {esc(status_label)}</span>
<span><b>المخطط:</b> {q3(po.qty_planned)}</span>
<span><b>المنتج:</b> {q3(po.qty_produced)}</span>
<span><b>الهالك:</b> {q3(po.qty_scrapped)}</span>
<span><b>مخزن الخامات:</b> {esc(po.raw_warehouse.name if po.raw_warehouse else '—')}</span>
<span><b>مخزن الناتج:</b> {esc(po.output_warehouse.name if po.output_warehouse else '—')}</span>
<span><b>المورد الصناعي:</b> {esc(po.subcontractor.name if po.subcontractor else '—')}</span>
<span><b>خط الإنتاج:</b> {esc(po.production_line.name if po.production_line else '—')}</span>
<span><b>تاريخ الجدولة:</b> {esc(po.scheduled_date or '—')}</span>
</div>
<h2>الخامات المصروفة</h2>
<table><thead><tr><th>المكوّن</th><th>الوحدة</th><th>الكمية</th><th>تكلفة الوحدة</th><th>الإجمالي</th></tr></thead><tbody>{rows_items}</tbody></table>
<h2>مسار التشغيل</h2>
<table><thead><tr><th>#</th><th>المرحلة</th><th>مركز التشغيل</th><th>دقائق/وحدة</th><th>الحالة</th></tr></thead><tbody>{rows_ops}</tbody></table>
<h2>دفعات الإنتاج</h2>
<table><thead><tr><th>رقم الدفعة</th><th>الكمية</th><th>التكلفة</th><th>الفحص</th></tr></thead><tbody>{rows_batches}</tbody></table>
<div class="totals">
<span>الخامات: <b>{_materials_cost(po):.2f} ج.م</b></span>
<span>الأجور والأعباء: <b>{_costs_total(po):.2f} ج.م</b></span>
<span>إجمالي التكلفة: <b>{_total_cost(po):.2f} ج.م</b></span>
</div>
{('<p style="font-size:13px"><b>ملاحظات:</b> ' + esc(po.notes).replace(chr(10), '<br>') + '</p>') if po.notes else ''}
<script>window.onload=function(){{window.print()}}</script>
</body></html>"""
    return Response(content=html, media_type="text/html; charset=utf-8")


@production_orders.post("/{order_id}/costs", response_model=schemas.ProductionOrderOut)
def add_production_cost(
    order_id: int,
    payload: schemas.ProductionCostIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """إضافة أجور تشغيل أو أعباء غير مباشرة على أمر التصنيع: مدين WIP / دائن حساب الاستحقاق."""
    po = _locked_po_or_404(db, order_id)
    if po.status not in ("draft", "in_progress"):
        raise HTTPException(status.HTTP_409_CONFLICT, "إضافة التكاليف متاحة للأوامر في المسودة أو قيد التنفيذ فقط")

    company_id = db.info["company_id"]
    wip_acc = _account_id_by_code(db, company_id, WIP_CODE)
    if payload.cost_type == "subcontract":
        if po.subcontractor_id is None:
            raise HTTPException(422, "تكلفة التصنيع الخارجي تتطلب تحديد مورد التصنيع الخارجي على الأمر")
        supplier = db.get(models.Supplier, po.subcontractor_id)
        link_party_coa(db, supplier, company_id, is_customer=False)
        credit_acc = supplier.chart_account_id
        if credit_acc is None:
            raise HTTPException(422, "لا يوجد حساب محاسبي مرتبط بالمورد")
    else:
        credit_acc = _account_id_by_code(db, company_id, COST_ACCOUNT[payload.cost_type])

    cost = models.ProductionCost(
        company_id=company_id,  # type: ignore
        order_id=po.id,  # type: ignore
        cost_type=payload.cost_type,  # type: ignore
        amount=payload.amount,  # type: ignore
        description=(payload.description or "").strip() or None,  # type: ignore
        created_by=user.id,  # type: ignore
    )
    db.add(cost)
    db.flush()

    AccountingEngine.create_entry(
        db=db,
        company_id=company_id,
        user_id=user.id,
        description=f"Production Order {po.code}: {COST_LABEL[payload.cost_type]}",
        items=[
            {"account_id": wip_acc, "debit": payload.amount, "credit": 0},
            {"account_id": credit_acc, "debit": 0, "credit": payload.amount},
        ],
        reference=po.code,
    )
    audit(db, user, "create", "production_cost", cost, f"{COST_LABEL[payload.cost_type]} {payload.amount} على {po.code}")
    db.commit()
    db.refresh(po)
    return _po_full_out(po)


@production_orders.delete("/{order_id}/costs/{cost_id}", response_model=schemas.ProductionOrderOut)
def delete_production_cost(
    order_id: int,
    cost_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """حذف تكلفة مضافة: عكس قيدها (مدين حساب الاستحقاق / دائن WIP)."""
    po = _locked_po_or_404(db, order_id)
    cost = db.get(models.ProductionCost, cost_id)
    if cost is None or cost.order_id != po.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Cost {cost_id} not found")
    if po.status not in ("draft", "in_progress"):
        raise HTTPException(status.HTTP_409_CONFLICT, "حذف التكاليف متاح للأوامر في المسودة أو قيد التنفيذ فقط")

    company_id = db.info["company_id"]
    wip_acc = _account_id_by_code(db, company_id, WIP_CODE)
    if cost.cost_type == "subcontract":
        supplier = db.get(models.Supplier, po.subcontractor_id) if po.subcontractor_id else None
        credit_acc = supplier.chart_account_id if supplier else None
        if credit_acc is None:
            raise HTTPException(422, "لا يمكن عكس قيد التصنيع الخارجي — المورد بلا حساب محاسبي مرتبط")
    else:
        credit_acc = _account_id_by_code(db, company_id, COST_ACCOUNT[cost.cost_type])
    AccountingEngine.create_entry(
        db=db,
        company_id=company_id,
        user_id=user.id,
        description=f"Production Order {po.code}: حذف {COST_LABEL[cost.cost_type]}",
        items=[
            {"account_id": credit_acc, "debit": cost.amount, "credit": 0},
            {"account_id": wip_acc, "debit": 0, "credit": cost.amount},
        ],
        reference=po.code,
    )
    audit(db, user, "delete", "production_cost", cost, f"حذف {COST_LABEL[cost.cost_type]} {cost.amount} من {po.code}")
    db.delete(cost)
    db.commit()
    db.refresh(po)
    return _po_full_out(po)


@production_orders.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_production_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    po = db.get(models.ProductionOrder, order_id)
    if po is None or po.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Production order {order_id} not found")
    if po.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "الحذف متاح فقط لأوامر في حالة مسودة")
    audit(db, user, "delete", "production_order", po, f"{po.code}")
    db.delete(po)
    db.commit()
    return None

# ---------------------------------------------------------------- production lines (خطوط الإنتاج)
lines = APIRouter(prefix="/production-lines", tags=["manufacturing"], dependencies=[Depends(get_current_user)])


@lines.get("", response_model=List[schemas.ProductionLineOut])
def list_production_lines(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return db.query(models.ProductionLine).filter(
        models.ProductionLine.company_id == db.info["company_id"]
    ).order_by(models.ProductionLine.name).all()


@lines.post("", response_model=schemas.ProductionLineOut, status_code=status.HTTP_201_CREATED)
def create_production_line(payload: schemas.ProductionLineIn, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    company_id = db.info["company_id"]
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "اسم خط الإنتاج مطلوب")
    if db.query(models.ProductionLine).filter(
        models.ProductionLine.company_id == company_id, models.ProductionLine.name == name
    ).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "اسم خط الإنتاج مستخدم بالفعل")
    line = models.ProductionLine(
        company_id=company_id,  # type: ignore
        name=name,  # type: ignore
        capacity_per_hour=payload.capacity_per_hour,  # type: ignore
        hourly_cost=payload.hourly_cost,  # type: ignore
    )
    db.add(line)
    db.commit()
    db.refresh(line)
    audit(db, user, "create", "production_line", line, name)
    return line


@lines.patch("/{line_id}", response_model=schemas.ProductionLineOut)
def update_production_line(line_id: int, payload: schemas.ProductionLineIn, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    line = db.get(models.ProductionLine, line_id)
    if line is None or line.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Production line {line_id} not found")
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "اسم خط الإنتاج مطلوب")
    dup = db.query(models.ProductionLine).filter(
        models.ProductionLine.company_id == db.info["company_id"],
        models.ProductionLine.name == name, models.ProductionLine.id != line_id,
    ).first()
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT, "اسم خط الإنتاج مستخدم بالفعل")
    line.name = name  # type: ignore
    line.capacity_per_hour = payload.capacity_per_hour  # type: ignore
    line.hourly_cost = payload.hourly_cost  # type: ignore
    audit(db, user, "update", "production_line", line, name)
    db.commit()
    db.refresh(line)
    return line


@lines.delete("/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_production_line(line_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    line = db.get(models.ProductionLine, line_id)
    if line is None or line.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Production line {line_id} not found")
    used = db.query(models.ProductionOrder).filter(models.ProductionOrder.production_line_id == line_id).count()
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, "لا يمكن حذف الخط — مستخدم في أوامر تصنيع")
    audit(db, user, "delete", "production_line", line, line.name)  # type: ignore
    db.delete(line)
    db.commit()
    return None