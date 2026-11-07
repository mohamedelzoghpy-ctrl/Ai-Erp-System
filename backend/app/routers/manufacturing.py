"""التصنيع (المرحلة 1): قوائم المواد (BOM) + أوامر التصنيع بصرف خامات وإنتاج دفعات وقيود تلقائية.

دورة أمر التصنيع: draft -> (issue: صرف خامات + قيد WIP) -> in_progress -> (produce batches) -> completed
الأرصدة تتحرك عبر move_stock (بأسباب production_issue / production_receive) والقيود عبر AccountingEngine.
"""

import math
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..accounting import AccountingEngine, link_party_coa, seed_default_coa
from ..audit import audit
from ..codegen import unique_code
from ..database import get_db
from ..deps import get_current_user, require_manager
from ..stock import move_stock

boms = APIRouter(prefix="/boms", tags=["manufacturing"], dependencies=[Depends(get_current_user)])
production_orders = APIRouter(prefix="/production-orders", tags=["manufacturing"], dependencies=[Depends(get_current_user)])

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


def _bom_out(db: Session, bom: models.Bom) -> models.Bom:
    for item in bom.items:
        item.component_name = item.component.name if item.component else None  # type: ignore[attr-defined]
        item.component_code = item.component.sku if item.component else None  # type: ignore[attr-defined]
        item.component_unit = item.component.unit if item.component else None  # type: ignore[attr-defined]
    return bom


def _po_out(po: models.ProductionOrder) -> models.ProductionOrder:
    po.product_name = po.product.name if po.product else None  # type: ignore[attr-defined]
    po.raw_warehouse_name = po.raw_warehouse.name if po.raw_warehouse else None  # type: ignore[attr-defined]
    po.output_warehouse_name = po.output_warehouse.name if po.output_warehouse else None  # type: ignore[attr-defined]
    po.subcontractor_name = po.subcontractor.name if po.subcontractor else None  # type: ignore[attr-defined]
    po.is_late = bool(
        po.scheduled_date
        and po.status in ("draft", "in_progress")
        and po.scheduled_date < date.today()
    )  # type: ignore[attr-defined]
    return po


def _po_full_out(po: models.ProductionOrder) -> models.ProductionOrder:
    _consumptions_out(po)
    # costs_total تُحسب تلقائيًا من property الموديل عند التسلسل
    return _po_out(po)


def _consumptions_out(po: models.ProductionOrder) -> models.ProductionOrder:
    for c in po.consumptions:
        c.component_name = c.component.name if c.component else None  # type: ignore[attr-defined]
        c.component_unit = c.component.unit if c.component else None  # type: ignore[attr-defined]
    return po


def _active_bom(db: Session, company_id: int, product_id: int) -> models.Bom:
    bom = (
        db.query(models.Bom)
        .filter(models.Bom.company_id == company_id, models.Bom.product_id == product_id, models.Bom.is_active.is_(True))
        .order_by(models.Bom.id.desc())
        .first()
    )
    if bom is None or not bom.items:
        raise HTTPException(422, "لا توجد قائمة مواد (BOM) مفعّلة لهذا المنتج — أنشئها أولًا")
    return bom


def _materials_cost(order: models.ProductionOrder) -> Decimal:
    return sum((Decimal(c.qty) * c.unit_cost for c in order.consumptions), Decimal("0"))


def _costs_total(order: models.ProductionOrder) -> Decimal:
    return sum((Decimal(c.amount or 0) for c in order.costs), Decimal("0"))


def _total_cost(order: models.ProductionOrder) -> Decimal:
    return _materials_cost(order) + _costs_total(order)


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
    if payload.is_active:
        # تفعيل إصدار واحد لكل منتج: أوقف إصدارات المنتج الأخرى
        db.query(models.Bom).filter(
            models.Bom.company_id == company_id,
            models.Bom.product_id == payload.product_id,
            models.Bom.is_active.is_(True),
        ).update({"is_active": False}, synchronize_session=False)

    bom = models.Bom(
        company_id=company_id,  # type: ignore
        product_id=payload.product_id,  # type: ignore
        version=payload.version.strip() or "v1",  # type: ignore
        output_qty=payload.output_qty,  # type: ignore
        is_active=payload.is_active,  # type: ignore
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
            notes=item.notes,  # type: ignore
        ))
    db.commit()
    db.refresh(bom)
    audit(db, user, "create", "bom", bom, f"{product.name} · {bom.version} · {len(payload.items)} مكوّن")
    db.refresh(bom)
    return _bom_out(db, bom)


@boms.get("/{bom_id}", response_model=schemas.BomOut)
def get_bom(bom_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    bom = db.get(models.Bom, bom_id)
    if bom is None or bom.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"BOM {bom_id} not found")
    return _bom_out(db, bom)


@boms.patch("/{bom_id}", response_model=schemas.BomOut)
def update_bom(bom_id: int, payload: schemas.BomCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    bom = db.get(models.Bom, bom_id)
    if bom is None or bom.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"BOM {bom_id} not found")
    product = db.get(models.Product, payload.product_id)
    if product is None or product.company_id != db.info["company_id"]:
        raise HTTPException(422, "المنتج غير موجود")
    if any(item.component_id == payload.product_id for item in payload.items):
        raise HTTPException(422, "المنتج النهائي لا يمكن أن يكون مكوّنًا في قائمته")
    component_ids = [item.component_id for item in payload.items]
    if len(component_ids) != len(set(component_ids)):
        raise HTTPException(422, "لا يمكن تكرار نفس المكوّن في القائمة")
    if payload.is_active and not bom.is_active:
        db.query(models.Bom).filter(
            models.Bom.company_id == db.info["company_id"],
            models.Bom.product_id == payload.product_id,
            models.Bom.id != bom.id,
            models.Bom.is_active.is_(True),
        ).update({"is_active": False}, synchronize_session=False)

    bom.product_id = payload.product_id  # type: ignore
    bom.version = payload.version.strip() or bom.version  # type: ignore
    bom.output_qty = payload.output_qty  # type: ignore
    bom.is_active = payload.is_active  # type: ignore
    bom.notes = payload.notes  # type: ignore
    bom.items.clear()
    db.flush()
    for item in payload.items:
        db.add(models.BomItem(
            company_id=bom.company_id,  # type: ignore
            bom_id=bom.id,  # type: ignore
            component_id=item.component_id,  # type: ignore
            qty_per_output=item.qty_per_output,  # type: ignore
            scrap_pct=item.scrap_pct,  # type: ignore
            notes=item.notes,  # type: ignore
        ))
    audit(db, user, "update", "bom", bom, f"{product.name} · {bom.version} · {len(payload.items)} مكوّن")
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


# ---------------------------------------------------------------- Production orders
@production_orders.get("", response_model=List[schemas.ProductionOrderOut])
def list_production_orders(
    product_id: Optional[int] = None,
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(draft|in_progress|completed|cancelled)$"),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.ProductionOrder).filter(models.ProductionOrder.company_id == db.info["company_id"])
    if product_id is not None:
        q = q.filter(models.ProductionOrder.product_id == product_id)
    if status_filter:
        q = q.filter(models.ProductionOrder.status == status_filter)
    rows = q.order_by(models.ProductionOrder.id.desc()).all()
    return [_po_full_out(po) for po in rows]


@production_orders.post("", response_model=schemas.ProductionOrderOut, status_code=status.HTTP_201_CREATED)
def create_production_order(
    payload: schemas.ProductionOrderCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
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

    bom = _active_bom(db, company_id, payload.product_id)
    if payload.bom_id is not None and payload.bom_id != bom.id:
        raise HTTPException(422, "قائمة المواد المختارة ليست القائمة المفعّلة لهذا المنتج")

    code = unique_code(db, models.ProductionOrder, company_id, product.name, "MO", max_length=50)
    po = models.ProductionOrder(
        company_id=company_id,  # type: ignore
        code=code,  # type: ignore
        product_id=payload.product_id,  # type: ignore
        bom_id=bom.id,  # type: ignore
        qty_planned=payload.qty_planned,  # type: ignore
        status="draft",  # type: ignore
        raw_warehouse_id=payload.raw_warehouse_id,  # type: ignore
        output_warehouse_id=payload.output_warehouse_id,  # type: ignore
        subcontractor_id=payload.subcontractor_id,  # type: ignore
        production_line=(payload.production_line or "").strip() or None,  # type: ignore
        scheduled_date=payload.scheduled_date,  # type: ignore
        notes=payload.notes,  # type: ignore
        created_by=user.id,  # type: ignore
    )
    db.add(po)
    db.commit()
    db.refresh(po)
    audit(db, user, "create", "production_order", po, f"{code} · {product.name} · {payload.qty_planned}")
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
    total_qty = 0
    by_product: dict = {}
    for po in rows:
        materials = _materials_cost(po)
        costs = _costs_total(po)
        total_o = materials + costs
        unit_cost = (total_o / Decimal(po.qty_planned)) if po.qty_planned else Decimal("0")
        allocated = (unit_cost * Decimal(po.qty_produced or 0)).quantize(Decimal("0.01"))
        variance = (total_o - allocated).quantize(Decimal("0.01"))
        total_materials += materials
        total_costs += costs
        total += total_o
        total_variance += variance
        total_qty += po.qty_produced or 0
        key = po.product_id
        entry = by_product.setdefault(key, {
            "product_id": po.product_id, "product_name": po.product.name if po.product else None,
            "orders": 0, "qty_produced": 0, "total": Decimal("0"),
        })
        entry["orders"] += 1
        entry["qty_produced"] += po.qty_produced or 0
        entry["total"] += total_o
        lines.append(schemas.ManufacturingReportLine(
            order_id=po.id, code=po.code,
            product_name=po.product.name if po.product else None,
            qty_planned=po.qty_planned, qty_produced=po.qty_produced or 0,
            materials=materials, costs=costs, total=total_o, unit_cost=unit_cost, variance=variance,
        ))
    by_product_list = [
        schemas.ManufacturingByProduct(**v) for _, v in sorted(by_product.items())
    ]
    return schemas.ManufacturingReportOut(
        date_from=date_from, date_to=date_to,
        lines=lines, total_orders=len(rows), total_qty_produced=total_qty,
        total_materials=total_materials, total_costs=total_costs,
        total=total, total_variance=total_variance, by_product=by_product_list,
    )


@production_orders.post("/{order_id}/issue", response_model=schemas.ProductionOrderOut)
def issue_production_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """بدء التشغيل: صرف الخامات من مخزن الخامات (بنسب القائمة × الكمية المخططة، تقريب لأعلى) + قيد WIP."""
    po = db.get(models.ProductionOrder, order_id)
    if po is None or po.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Production order {order_id} not found")
    if po.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "الصرف متاح فقط لأوامر التصنيع في حالة مسودة")

    company_id = db.info["company_id"]
    bom = po.bom
    if bom is None or not bom.items:
        raise HTTPException(422, "أمر التصنيع بدون قائمة مواد")
    raw_wh = po.raw_warehouse
    wip_acc = _account_id_by_code(db, company_id, WIP_CODE)
    inventory_acc = _account_id_by_code(db, company_id, INVENTORY_CODE)

    # حساب المطلوب من كل مكوّن: (الكمية لكل وحدة × (1 + الفاقد)) × المخطط / كمية الناتج — تقريب لأعلى
    requirements = []
    total_cost = Decimal("0")
    for item in sorted(bom.items, key=lambda it: it.id):
        if item.component_id == po.product_id:
            raise HTTPException(422, "المنتج النهائي لا يمكن أن يكون مكوّنًا في قائمته")
        required = int(math.ceil(
            float(item.qty_per_output) * (1 + float(item.scrap_pct) / 100) * po.qty_planned / max(bom.output_qty, 1)
        ))
        if required <= 0:
            required = 1
        component = db.get(models.Product, item.component_id)
        if component is None or component.company_id != company_id:
            raise HTTPException(422, f"المكوّن {item.component_id} غير موجود")
        unit_cost = Decimal(component.cost_price or 0)
        total_cost += Decimal(required) * unit_cost
        requirements.append((component, required, unit_cost))

    # صرف كل الخامات مرة واحدة (all-or-nothing): move_stock يرفع 409 عند نقص أي خامة
    for component, required, _unit_cost in requirements:
        move_stock(db, component, po.raw_warehouse_id, -required, "production_issue", reference=po.code)

    for component, required, unit_cost in requirements:
        db.add(models.ProductionConsumption(
            company_id=company_id,  # type: ignore
            order_id=po.id,  # type: ignore
            component_id=component.id,  # type: ignore
            qty=required,  # type: ignore
            unit_cost=unit_cost,  # type: ignore
        ))

    if total_cost > 0:
        AccountingEngine.create_entry(
            db=db,
            company_id=company_id,
            user_id=user.id,
            description=f"Production Order {po.code}: صرف خامات",
            items=[
                {"account_id": wip_acc, "debit": total_cost, "credit": 0},
                {"account_id": inventory_acc, "debit": 0, "credit": total_cost},
            ],
            reference=po.code,
        )

    po.status = "in_progress"  # type: ignore

    # التصنيع المرحلي: مكوّن له قائمة مواد مفعّلة -> أنشئ له أمر تصنيع فرعي (مسودة) بنفس الكمية المطلوبة
    children_created = []
    for component, required, _unit_cost in requirements:
        has_own_bom = db.query(models.Bom).filter(
            models.Bom.company_id == company_id,
            models.Bom.product_id == component.id,
            models.Bom.is_active.is_(True),
        ).first()
        if has_own_bom is None:
            continue
        child_code = unique_code(db, models.ProductionOrder, company_id, component.name, "MO", max_length=50)
        child = models.ProductionOrder(
            company_id=company_id,  # type: ignore
            code=child_code,  # type: ignore
            product_id=component.id,  # type: ignore
            bom_id=has_own_bom.id,  # type: ignore
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
        children_created.append(child.code)
        audit(db, user, "create", "production_order", child, f"أمر فرعي تلقائي من {po.code} — {component.name} × {required}")

    audit(db, user, "update", "production_order", po, f"بدء تشغيل {po.code} — صرف خامات {total_cost}" + (f" · أوامر فرعية: {', '.join(children_created)}" if children_created else ""))
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
    po = db.get(models.ProductionOrder, order_id)
    if po is None or po.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Production order {order_id} not found")
    if po.status != "in_progress":
        raise HTTPException(status.HTTP_409_CONFLICT, "الإنتاج متاح فقط لأوامر قيد التنفيذ")
    remaining = po.qty_planned - po.qty_produced
    if payload.qty > remaining:
        raise HTTPException(422, f"الكمية المطلوبة أكبر من المتبقي للتشغيل ({remaining})")

    company_id = db.info["company_id"]
    out_wh = po.output_warehouse
    wip_acc = _account_id_by_code(db, company_id, WIP_CODE)
    inventory_acc = _account_id_by_code(db, company_id, INVENTORY_CODE)

    product = po.product
    # تكلفة الوحدة المخصصة = إجمالي (الخامات + الأجور والأعباء) / الكمية المخططة
    total_cost = _total_cost(po)
    unit_cost = (total_cost / Decimal(po.qty_planned)) if po.qty_planned else Decimal("0")
    batch_cost = (unit_cost * Decimal(payload.qty)).quantize(Decimal("0.01"))

    # متوسط مرجح لتكلفة المنتج
    old_qty = product.quantity or 0
    old_cost = Decimal(product.cost_price or 0)
    new_total_qty = old_qty + payload.qty
    if new_total_qty > 0:
        product.cost_price = ((Decimal(old_qty) * old_cost + batch_cost) / Decimal(new_total_qty)).quantize(Decimal("0.01"))  # type: ignore

    move_stock(db, product, po.output_warehouse_id, payload.qty, "production_receive", reference=po.code)

    if batch_cost > 0:
        AccountingEngine.create_entry(
            db=db,
            company_id=company_id,
            user_id=user.id,
            description=f"Production Order {po.code}: إنتاج {payload.qty}",
            items=[
                {"account_id": inventory_acc, "debit": batch_cost, "credit": 0},
                {"account_id": wip_acc, "debit": 0, "credit": batch_cost},
            ],
            reference=po.code,
        )

    po.qty_produced = (po.qty_produced or 0) + payload.qty  # type: ignore
    batch_seq = db.query(models.ProductionBatch).filter(models.ProductionBatch.order_id == po.id).count() + 1
    db.add(models.ProductionBatch(
        company_id=company_id,  # type: ignore
        order_id=po.id,  # type: ignore
        batch_no=f"{po.code}-B{batch_seq}",  # type: ignore
        qty=payload.qty,  # type: ignore
        cost=batch_cost,  # type: ignore
    ))
    if po.qty_produced >= po.qty_planned:  # type: ignore
        po.status = "completed"  # type: ignore
        po.completed_at = datetime.now(timezone.utc)  # type: ignore
    audit(db, user, "update", "production_order", po, f"إنتاج {payload.qty} من {po.qty_planned} — تكلفة الدفعة {batch_cost}")
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
    po = db.get(models.ProductionOrder, order_id)
    if po is None or po.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Production order {order_id} not found")
    if po.status != "in_progress":
        raise HTTPException(status.HTTP_409_CONFLICT, "الإنهاء متاح فقط لأوامر قيد التنفيذ")

    company_id = db.info["company_id"]
    wip_acc = _account_id_by_code(db, company_id, WIP_CODE)
    variance_acc = _account_id_by_code(db, company_id, VARIANCE_CODE)

    total_cost = _total_cost(po)
    unit_cost = (total_cost / Decimal(po.qty_planned)) if po.qty_planned else Decimal("0")
    allocated = (unit_cost * Decimal(po.qty_produced or 0)).quantize(Decimal("0.01"))
    variance = (total_cost - allocated).quantize(Decimal("0.01"))

    if variance != 0:
        AccountingEngine.create_entry(
            db=db,
            company_id=company_id,
            user_id=user.id,
            description=f"Production Order {po.code}: فروق تصنيع",
            items=(
                [
                    {"account_id": variance_acc, "debit": variance, "credit": 0},
                    {"account_id": wip_acc, "debit": 0, "credit": variance},
                ] if variance > 0 else
                [
                    {"account_id": wip_acc, "debit": -variance, "credit": 0},
                    {"account_id": variance_acc, "debit": 0, "credit": -variance},
                ]
            ),
            reference=po.code,
        )

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
    po = db.get(models.ProductionOrder, order_id)
    if po is None or po.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Production order {order_id} not found")
    batch = db.get(models.ProductionBatch, batch_id)
    if batch is None or batch.order_id != po.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Batch {batch_id} not found")
    if batch.qc_status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "تم الفحص من قبل — الدفعة ليس pending")

    if payload.result == "rejected":
        product = po.product
        move_stock(db, product, po.output_warehouse_id, -batch.qty, "production_reject", reference=batch.batch_no)
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
    batch.qc_status = payload.result  # type: ignore
    audit(db, user, "update", "production_batch", batch, f"فحص {batch.batch_no}: {payload.result}")
    db.commit()
    db.refresh(po)
    return _po_out(po)


@production_orders.post("/{order_id}/scrape", response_model=schemas.ProductionOrderOut)
def scrape_production_order(
    order_id: int,
    payload: schemas.ProductionScrapIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """تسجيل هالك من أمر قيد التشغيل: الكمية الهالكة تُرحّل من WIP لمصروف هالك."""
    po = db.get(models.ProductionOrder, order_id)
    if po is None or po.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Production order {order_id} not found")
    if po.status != "in_progress":
        raise HTTPException(status.HTTP_409_CONFLICT, "الهالك متاح فقط لأوامر قيد التنفيذ")
    remaining_planned = po.qty_planned - (po.qty_produced or 0) - (po.qty_scrapped or 0)
    if payload.qty > remaining_planned:
        raise HTTPException(422, f"كمية الهالك أكبر من المتبقي للتشغيل ({remaining_planned})")

    company_id = db.info["company_id"]
    wip_acc = _account_id_by_code(db, company_id, WIP_CODE)
    scrap_acc = _account_id_by_code(db, company_id, SCRAP_CODE)
    unit_cost = (_total_cost(po) / Decimal(po.qty_planned)) if po.qty_planned else Decimal("0")
    scrap_cost = (unit_cost * Decimal(payload.qty)).quantize(Decimal("0.01"))

    if scrap_cost > 0:
        AccountingEngine.create_entry(
            db=db,
            company_id=company_id,
            user_id=user.id,
            description=f"Production Order {po.code}: هالك {payload.qty}",
            items=[
                {"account_id": scrap_acc, "debit": scrap_cost, "credit": 0},
                {"account_id": wip_acc, "debit": 0, "credit": scrap_cost},
            ],
            reference=po.code,
        )

    po.qty_scrapped = (po.qty_scrapped or 0) + payload.qty  # type: ignore
    audit(db, user, "update", "production_order", po, f"هالك {payload.qty} من {po.code} — {scrap_cost}")
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
            qty_planned=po.qty_planned, qty_produced=po.qty_produced or 0,
            remaining=po.qty_planned - (po.qty_produced or 0),
            materials=materials, costs=costs, wip_value=total,
            unit_cost=(total / Decimal(po.qty_planned)) if po.qty_planned else Decimal("0"),
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
    po = db.get(models.ProductionOrder, order_id)
    if po is None or po.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Production order {order_id} not found")
    if po.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "الإلغاء متاح فقط لأوامر في حالة مسودة (قبل صرف الخامات)")
    po.status = "cancelled"  # type: ignore
    audit(db, user, "update", "production_order", po, f"إلغاء {po.code}")
    db.commit()
    db.refresh(po)
    return _po_out(po)


@production_orders.post("/{order_id}/costs", response_model=schemas.ProductionOrderOut)
def add_production_cost(
    order_id: int,
    payload: schemas.ProductionCostIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """إضافة أجور تشغيل أو أعباء غير مباشرة على أمر التصنيع: مدين WIP / دائن حساب الاستحقاق."""
    po = db.get(models.ProductionOrder, order_id)
    if po is None or po.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Production order {order_id} not found")
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
    po = db.get(models.ProductionOrder, order_id)
    if po is None or po.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Production order {order_id} not found")
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