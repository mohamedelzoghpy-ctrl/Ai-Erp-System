"""Point of sale: one request creates the sale, takes the stock and records the payment atomically."""

import os
from datetime import datetime
from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from .. import exports, models, schemas
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user, user_role
from ..pagination import paginate
from ..permissions import user_has_permission
from .orders import _require, apply_sale_stock
from .shifts import open_shift_of

router = APIRouter(prefix="/pos", tags=["pos"])

WALK_IN_NAME = "عميل نقدي"
# Set POS_REQUIRE_SHIFT=true to force cashiers to open a drawer shift before selling.
REQUIRE_SHIFT = os.getenv("POS_REQUIRE_SHIFT", "false").lower() in ("1", "true", "yes")


def _walk_in(db: Session) -> models.Customer:
    company_id = db.info.get("company_id")
    c = db.query(models.Customer).filter(
        models.Customer.name == WALK_IN_NAME, models.Customer.company_id == company_id  # type: ignore
    ).order_by(models.Customer.id).first()
    if c is None:
        from ..codegen import unique_code
        c = models.Customer(company_id=company_id, name=WALK_IN_NAME, code=unique_code(db, models.Customer, company_id, WALK_IN_NAME, "C"))  # type: ignore
        db.add(c)
        db.flush()
    return c


def _load_checkout_products(db: Session, items) -> dict[int, models.Product]:
    product_ids = list(dict.fromkeys(item.product_id for item in items))
    if not product_ids:
        return {}

    products = db.query(models.Product).filter(models.Product.id.in_(product_ids)).all()
    products_by_id = {product.id: product for product in products}
    missing_id = next((product_id for product_id in product_ids if product_id not in products_by_id), None)
    if missing_id is not None:
        raise HTTPException(422, f"Product {missing_id} does not exist")
    return products_by_id  # type: ignore


@router.get("/invoices", response_model=List[schemas.SalesOrderOut])
def list_pos_invoices(response: Response, skip: int = 0, limit: int = 50, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    query = db.query(models.SalesOrder).filter(models.SalesOrder.status == "confirmed")
    if user_role(user) not in ("admin", "manager"):
        query = query.filter(models.SalesOrder.created_by == user.id)
    invoices = paginate(query, response, skip, min(limit, 100), models.SalesOrder.id.desc())
    from ..accounts import attach_settlement
    attach_settlement(db, "customer", invoices)
    return invoices


@router.post("/checkout", response_model=schemas.PosReceipt, status_code=status.HTTP_201_CREATED)
def checkout(payload: schemas.PosCheckout, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if REQUIRE_SHIFT and open_shift_of(db, user.id) is None:  # type: ignore
        raise HTTPException(status.HTTP_409_CONFLICT, "Open a shift before selling")
    _require(db, models.Warehouse, payload.warehouse_id, "Warehouse")
    if payload.customer_id is not None:
        customer = _require(db, models.Customer, payload.customer_id, "Customer")
        if not customer.is_active:  # type: ignore
            raise HTTPException(422, "Customer is inactive")
    else:
        customer = _walk_in(db)

    products = _load_checkout_products(db, payload.items)
    # أسعار قائمة العميل (تتجاوز سعر البيع العام للأصناف الموجودة فيها)
    from ..pricing import list_price_map
    list_prices = list_price_map(db, getattr(customer, "price_list_id", None) or 0) if customer is not None else {}
    # صلاحية تعديل سعر البيع: رفع السعر فوق المعتمد يتطلب الصلاحية.
    # الخصم يُرسل كبنود مجزأة بأقل من السعر — يبقى متاحاً كما هو (سلوك محفوظ).
    perms = getattr(request.state, "permissions", None)
    if perms is not None and "*" not in perms and not user_has_permission(perms, "sales.order.price_increase"):
        grouped: dict = {}
        for item in payload.items:
            p = products[item.product_id]
            price = item.unit_price if item.unit_price is not None else (list_prices.get(p.id) or p.sale_price)
            qty, amount = grouped.get(p.id, (Decimal("0"), Decimal("0")))
            grouped[p.id] = (qty + Decimal(str(item.quantity)), amount + price * Decimal(str(item.quantity)))
        for pid, (qty, amount) in grouped.items():
            list_price = list_prices.get(pid) or products[pid].sale_price
            if list_price is not None and amount > list_price * qty:
                raise HTTPException(403, "رفع سعر البيع فوق المعتمد يتطلب صلاحية «تعديل سعر البيع»")
    order = models.SalesOrder(customer_id=customer.id, warehouse_id=payload.warehouse_id, notes=payload.notes, created_by=user.id, rep_id=payload.rep_id if payload.rep_id and db.get(models.SalesRep, payload.rep_id) else None)  # type: ignore
    total = Decimal("0")
    for item in payload.items:
        product = products[item.product_id]
        if not product.is_active:  # type: ignore
            raise HTTPException(422, f"Product '{product.name}' is inactive")
        price = item.unit_price if item.unit_price is not None else (list_prices.get(product.id) or product.sale_price)
        order.items.append(
            models.SalesOrderItem(product_id=product.id, quantity=item.quantity, unit_price=price, unit_cost=product.cost_price)  # type: ignore
        )
        total += price * Decimal(str(item.quantity))
    total = total.quantize(Decimal("0.01"))  # المبالغ المالية منزلتان دائمًا
    # ضريبة القيمة المضافة على البيع النقدي: الإجمالي المدفوع = الصافي + الضريبة
    tax_rate = Decimal(str(getattr(payload, "tax_rate", 0) or 0))
    tax_amount = (total * tax_rate / Decimal("100")).quantize(Decimal("0.01"))
    order.subtotal = total  # type: ignore
    order.tax_rate = tax_rate  # type: ignore
    order.tax_amount = tax_amount  # type: ignore
    total = total + tax_amount  # الإجمالي شامل الضريبة
    order.total_amount = total  # type: ignore

    if payload.payments:
        paid = sum((leg.amount for leg in payload.payments), Decimal("0"))
    else:
        paid = total if payload.amount_paid is None else payload.amount_paid
    if paid > total:  # type: ignore
        raise HTTPException(422, "amount_paid cannot exceed the total (give change at the till)")
    if payload.customer_id is None and paid != total:  # type: ignore
        raise HTTPException(422, "A walk-in customer must pay in full; choose a customer to sell on credit")
    # الحد الائتماني: فقط الجزء الآجل من الفاتورة يزيد المديونية
    if payload.customer_id is not None:
        from ..accounts import check_credit_limit
        check_credit_limit(db, payload.customer_id, total - paid, perms=perms)

    db.add(order)
    db.flush()
    apply_sale_stock(db, order, allow_expired=False)  # POS: حجب اللوطات المنتهية دائمًا
    order.status = "confirmed"  # type: ignore
    # أصناف متتبعة بالأرقام التسلسلية: اختيار آلي (الأقدم أولًا) من مخزن البيع
    from .orders import _bind_sale_serials
    _bind_sale_serials(db, order)

    # ---- Accounting: a POS sale posts the same journals as a confirmed sales order. ----
    from ..accounting import AccountingEngine, link_bank_coa, link_party_coa, link_safe_coa, seed_default_coa
    company_id = db.info["company_id"]
    seed_default_coa(db, company_id)
    link_party_coa(db, customer, company_id, is_customer=True)

    cash_acc_id = None
    if payload.bank_id is not None:
        bank = db.get(models.Bank, payload.bank_id)
        if bank is None or bank.company_id != company_id or not bank.is_active:  # type: ignore
            raise HTTPException(422, "Bank is inactive or does not belong to the company")
        link_bank_coa(db, bank, company_id)
        cash_acc_id = bank.chart_account_id
    elif payload.safe_id is not None:
        safe = db.get(models.Safe, payload.safe_id)
        if safe is None or safe.company_id != company_id or not safe.is_active:  # type: ignore
            raise HTTPException(422, "Safe is inactive or does not belong to the company")
        link_safe_coa(db, safe, company_id)
        cash_acc_id = safe.chart_account_id

    # الدفع المقسّم: سطر لكل وسيلة (نقدًا خزينة + فيزا بنك في فاتورة واحدة)
    if payload.payments:
        legs: list = []
        for leg in payload.payments:
            if leg.method == "cheque":
                raise HTTPException(422, "الدفع المقسّم لا يدعم الشيك — سجّل الشيك من حافظة الشيكات")
            legs.append(leg)
        if len({(leg.safe_id, leg.bank_id) for leg in legs}) == 1 and len(legs) > 1:
            raise HTTPException(422, "الدفع المقسّم يتطلب وجهتي استلام مختلفتين")
    else:
        legs = []
    payment = None
    payments_created: list = []
    if paid > 0:  # type: ignore
        if legs:
            for idx, leg in enumerate(legs, 1):
                payment = models.Payment(
                    kind="receipt", customer_id=customer.id,  # type: ignore
                    safe_id=leg.safe_id, bank_id=leg.bank_id, amount=leg.amount,  # type: ignore
                    method=leg.method, reference=f"SO-{order.id}-{idx}",  # type: ignore
                    paid_on=datetime.now(exports.LOCAL_TZ).date(), created_by=user.id,  # type: ignore
                )
                db.add(payment)
                db.flush()
                payments_created.append(payment)
        else:
            payment = models.Payment(
                kind="receipt",  # type: ignore
                customer_id=customer.id,  # type: ignore
                safe_id=payload.safe_id,  # type: ignore
                bank_id=payload.bank_id,  # type: ignore
                amount=paid,  # type: ignore
                method=payload.method,  # type: ignore
                reference=f"SO-{order.id}",  # type: ignore
                paid_on=datetime.now(exports.LOCAL_TZ).date(),  # type: ignore
                created_by=user.id,  # type: ignore
            )
            db.add(payment)
            db.flush()
            payments_created.append(payment)

    # 1) Revenue: Debit Customer/Cash-side (gross), Credit Sales Revenue (net), Credit VAT output (tax).
    from ..accounting import VAT_OUTPUT_CODE
    revenue_acc = db.query(models.ChartAccount).filter(
        models.ChartAccount.company_id == company_id, models.ChartAccount.code == "4101"
    ).first()
    if not revenue_acc or not customer.chart_account_id:
        db.rollback()
        raise HTTPException(409, "Sales accounting accounts could not be initialized")
    sale_items = [
        {"account_id": customer.chart_account_id, "debit": total, "credit": 0},
        {"account_id": revenue_acc.id, "debit": 0, "credit": order.subtotal},
    ]
    if tax_amount > 0:
        vat_acc = db.query(models.ChartAccount).filter(
            models.ChartAccount.company_id == company_id, models.ChartAccount.code == VAT_OUTPUT_CODE
        ).first()
        if vat_acc is None or vat_acc.is_group:
            db.rollback()
            raise HTTPException(409, "حساب ضريبة القيمة المضافة (2130) غير موجود — حدّث شجرة الحسابات")
        sale_items.append({"account_id": vat_acc.id, "debit": 0, "credit": tax_amount})
    AccountingEngine.create_entry(
        db=db,
        company_id=company_id,
        user_id=user.id,
        description=f"POS Sale SO-{order.id}",
        items=sale_items,
        reference=f"SO-{order.id}",
    )

    # 2) COGS: Debit COGS, Credit Inventory at the cost frozen on the order lines.
    cogs_total = sum(((it.unit_cost or Decimal("0")) * Decimal(str(it.quantity)) for it in order.items), Decimal("0"))
    if cogs_total > 0:
        inventory_acc = db.query(models.ChartAccount).filter(
            models.ChartAccount.company_id == company_id, models.ChartAccount.code == "1101"
        ).first()
        cogs_acc = db.query(models.ChartAccount).filter(
            models.ChartAccount.company_id == company_id, models.ChartAccount.code == "5100"
        ).first()
        if not inventory_acc or not cogs_acc:
            db.rollback()
            raise HTTPException(409, "COGS accounting accounts could not be initialized")
        AccountingEngine.create_entry(
            db=db,
            company_id=company_id,
            user_id=user.id,
            description=f"COGS SO-{order.id}",
            items=[
                {"account_id": cogs_acc.id, "debit": cogs_total, "credit": 0},
                {"account_id": inventory_acc.id, "debit": 0, "credit": cogs_total},
            ],
            reference=f"SO-{order.id}",
        )

    # 3) Payment: Debit Cash (safe/bank), Credit Customer — سند/قيد لكل وسيلة دفع.
    from ..accounting import link_bank_coa as _link_bank, link_safe_coa as _link_safe
    for leg_idx, pay in enumerate(payments_created, 1):
        leg_acc_id = None
        if pay.bank_id is not None:
            bank = db.get(models.Bank, pay.bank_id)
            if bank is None or bank.company_id != company_id or not bank.is_active:
                raise HTTPException(422, "بنك غير صالح في سطر الدفع")
            _link_bank(db, bank, company_id)
            leg_acc_id = bank.chart_account_id
            bank.balance = (bank.balance or 0) + pay.amount  # type: ignore[operator]
        elif pay.safe_id is not None:
            safe = db.get(models.Safe, pay.safe_id)
            if safe is None or safe.company_id != company_id or not safe.is_active:
                raise HTTPException(422, "خزينة غير صالحة في سطر الدفع")
            _link_safe(db, safe, company_id)
            leg_acc_id = safe.chart_account_id
            safe.balance = (safe.balance or 0) + pay.amount  # type: ignore[operator]
        if leg_acc_id and customer.chart_account_id:
            AccountingEngine.create_entry(
                db=db,
                company_id=company_id,
                user_id=user.id,
                description=f"POS Receipt SO-{order.id}",
                items=[
                    {"account_id": leg_acc_id, "debit": pay.amount, "credit": 0},
                    {"account_id": customer.chart_account_id, "debit": 0, "credit": pay.amount},
                ],
                reference=f"SO-{order.id}-{leg_idx}" if len(payments_created) > 1 else f"SO-{order.id}",
            )
        else:
            import logging
            logging.getLogger(__name__).warning(
                "POS SO-%s: payment %s has no safe/bank; cash leg skipped in double-entry", order.id, pay.id
            )

    audit(db, user, "pos_sale", "sales_order", order, f"إجمالي {total} · مدفوع {paid} · {customer.name}")
    db.commit()
    return schemas.PosReceipt(
        order_id=order.id,  # type: ignore
        customer_id=customer.id,  # type: ignore
        customer_name=customer.name,  # type: ignore
        total=total,  # type: ignore
        paid=paid,  # type: ignore
        balance_due=total - paid,  # type: ignore
        payment_id=payments_created[0].id if payments_created else None,  # type: ignore
    )
