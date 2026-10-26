"""Seed a fresh database with a starter warehouse, supplier, customer and products.

Usage (after first-run setup, or against a test DB):
    DATABASE_URL=postgresql+psycopg2://... python backend/scripts/seed.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session

from app import models, stock
from app.database import SessionLocal

DEFAULT_PRODUCTS = [
    ("SKU-001", "منتج تجريبي 1", "قطعة", "10.00", "15.00", 50, 10),
    ("SKU-002", "منتج تجريبي 2", "كرتون", "25.00", "40.00", 20, 5),
    ("SKU-003", "منتج تجريبي 3", "كيلو", "5.00", "8.00", 100, 20),
]


def seed(db: Session) -> None:
    company = db.query(models.Company).filter(models.Company.code == "default").one_or_none()
    if company is None:
        print("No default company found. Run first-run setup first.")
        return
    branch = db.query(models.Branch).filter(models.Branch.company_id == company.id).first()
    if branch is None:
        branch = models.Branch(company_id=company.id, name="Main Branch", code="main")
        db.add(branch)
        db.flush()

    wh = db.query(models.Warehouse).filter(models.Warehouse.company_id == company.id).first()
    if wh is None:
        wh = models.Warehouse(company_id=company.id, branch_id=branch.id, name="المخزن الرئيسي", code="MAIN", location="المستودع")
        db.add(wh)
        db.flush()
        print(f"Created warehouse: {wh.name}")
    else:
        print(f"Warehouse exists: {wh.name}")

    sup = db.query(models.Supplier).filter(models.Supplier.company_id == company.id).first()
    if sup is None:
        sup = models.Supplier(company_id=company.id, name="مورد تجريبي", phone="0000000000")
        db.add(sup)
        db.flush()
        print(f"Created supplier: {sup.name}")

    cus = db.query(models.Customer).filter(models.Customer.company_id == company.id).first()
    if cus is None:
        cus = models.Customer(company_id=company.id, name="عميل تجريبي", phone="0000000000")
        db.add(cus)
        db.flush()
        print(f"Created customer: {cus.name}")

    created = 0
    for sku, name, unit, cost, sale, qty, reorder in DEFAULT_PRODUCTS:
        if db.query(models.Product).filter(models.Product.sku == sku, models.Product.company_id == company.id).first():
            continue
        p = models.Product(
            company_id=company.id,
            sku=sku,
            name=name,
            unit=unit,
            cost_price=cost,
            sale_price=sale,
            quantity=0,
            reorder_level=reorder,
            warehouse_id=wh.id,
            supplier_id=sup.id,
            is_active=True,
        )
        db.add(p)
        db.flush()
        if qty:
            stock.move_stock(db, p, wh.id, int(qty), "adjustment", "opening balance")
        created += 1
    db.commit()
    print(f"Seed complete: {created} new products added.")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()