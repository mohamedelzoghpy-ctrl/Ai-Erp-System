"""التسعير: حل السعر الفعلي للصنف حسب قائمة أسعار العميل.

القاعدة: قائمة العميل أولًا (إن كانت تحتوي الصنف) — وإلا سعر البيع العام.
هذا «السعر المعتمد» الذي تُقاس عليه صلاحية تعديل سعر البيع (الزيادة فقط).
"""
from decimal import Decimal

from sqlalchemy.orm import Session

from . import models


def list_price_map(db: Session, price_list_id: int) -> dict:
    """خريطة {product_id: unit_price} لقائمة واحدة (صالحة ونشطة)."""
    if not price_list_id:
        return {}
    pl = db.query(models.PriceList).filter(
        models.PriceList.id == price_list_id,
        models.PriceList.company_id == db.info["company_id"],
        models.PriceList.is_active.is_(True),
    ).first()
    if pl is None:
        return {}
    return {
        pid: Decimal(str(price))
        for pid, price in db.query(models.PriceListItem.product_id, models.PriceListItem.unit_price)
        .filter(models.PriceListItem.price_list_id == pl.id)
        .all()
    }


def effective_base_price(db: Session, product: "models.Product", customer: "models.Customer | None") -> Decimal:
    """السعر المعتمد للصنف لهذا العميل: قائمته ثم سعر البيع العام."""
    if customer is not None and getattr(customer, "price_list_id", None):
        price = list_price_map(db, customer.price_list_id).get(product.id)
        if price is not None:
            return price
    return Decimal(str(product.sale_price or 0))


def resolve_currency(db: Session, currency_id) -> "tuple[models.Currency, Decimal] | tuple[None, None]":
    """يعيد (العملة، السعر) إن حُددت عملة صالحة، وإلا (None, None) أي جنيه."""
    if not currency_id:
        return None, None
    c = db.query(models.Currency).filter(
        models.Currency.id == currency_id,
        models.Currency.company_id == db.info["company_id"],
        models.Currency.is_active.is_(True),
    ).first()
    if c is None:
        return None, None
    return c, Decimal(str(c.rate))


def to_base(foreign: Decimal, rate: Decimal) -> Decimal:
    """تحويل مبلغ أجنبي إلى الجنيه (منزلتان)."""
    return (Decimal(str(foreign)) * Decimal(str(rate))).quantize(Decimal("0.01"))
