"""Accounting engine tests for MOZAD ERP - double-entry bookkeeping."""

import pytest
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app import models
from app.accounting import (
    AccountingEngine,
    seed_default_coa,
    link_safe_coa,
    link_bank_coa,
    link_party_coa,
    ensure_company_coa,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        pass  # create_entry ثابت — لا محرك يُغلق


@pytest.fixture()
def company(db):
    """Create a test company with default CoA."""
    company = models.Company(name="Test Co", code="TEST-001", is_active=True)
    db.add(company)
    db.commit()
    db.refresh(company)
    seed_default_coa(db, company.id)
    return company


# -----------------------------------------------------------------------
# Seed / CoA tests
# -----------------------------------------------------------------------

def test_seed_default_coa_creates_all_accounts(db, company):
    """Default CoA should have all standard accounts."""
    seed_default_coa(db, company.id)
    accounts = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company.id).all()
    codes = {a.code for a in accounts}
    assert "1111" in codes  # Cash (الصندوق)
    assert "1112" in codes  # Banks (حساب بنكي)
    assert "1120" in codes  # Receivables (ذمم العملاء)
    assert "2110" in codes  # Payables (ذمم الموردين)
    assert "3000" in codes  # Equity
    assert "4101" in codes  # Revenue (إيرادات المبيعات)
    assert "5200" in codes  # Expenses (تشغيلية)
    assert len(accounts) >= 50


def test_account_balances_start_at_zero(db, company):
    """All new accounts start with zero balance."""
    seed_default_coa(db, company.id)
    accounts = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company.id).all()
    for acc in accounts:
        assert acc.balance == 0


def test_ensure_company_coa_idempotent(db, company):
    """Calling ensure_company_coa multiple times should not duplicate."""
    ensure_company_coa(db, company.id)
    count1 = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company.id).count()
    ensure_company_coa(db, company.id)
    count2 = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company.id).count()
    assert count1 == count2


# -----------------------------------------------------------------------
# Journal Entry / AccountingEngine tests
# -----------------------------------------------------------------------

def test_journal_entry_double_entry_balances(db, company):
    """Every journal entry must balance (debits == credits)."""
    seed_default_coa(db, company.id)
    engine = AccountingEngine

    cash = db.query(models.ChartAccount).filter_by(company_id=company.id, code="1111").first()
    capital = db.query(models.ChartAccount).filter_by(company_id=company.id, code="3100").first()

    entry = engine.create_entry(
        db=db,
        company_id=company.id,
        user_id=None,
        description="Invest cash",
        items=[
            {"account_id": cash.id, "debit": Decimal("1000"), "credit": Decimal("0")},
            {"account_id": capital.id, "debit": Decimal("0"), "credit": Decimal("1000")},
        ],
        reference="JE-001",
        date="2026-01-15",
    )

    assert entry is not None
    assert cash.balance == Decimal("1000")
    # اصطلاح المنتج: الحسابات ذات الطبيعة الدائنة (حقوق ملكية) يزيد رصيدها بالموجب
    assert capital.balance == Decimal("1000.00")


def test_journal_entry_must_balance(db, company):
    """Unbalanced journal entry must raise an error."""
    seed_default_coa(db, company.id)
    engine = AccountingEngine

    cash = db.query(models.ChartAccount).filter_by(company_id=company.id, code="1111").first()
    capital = db.query(models.ChartAccount).filter_by(company_id=company.id, code="3100").first()

    with pytest.raises(ValueError, match="must balance"):
        engine.create_entry(
            db=db,
            company_id=company.id,
            user_id=None,
            description="Bad entry",
            items=[
                {"account_id": cash.id, "debit": Decimal("1000"), "credit": Decimal("0")},
                {"account_id": capital.id, "debit": Decimal("0"), "credit": Decimal("500")},
            ],
            reference="JE-002",
            date="2026-01-15",
        )


def test_journal_entry_requires_existing_accounts(db, company):
    """Journal entry with non-existent account must fail (HTTP 422 since the central guard)."""
    from fastapi import HTTPException

    seed_default_coa(db, company.id)
    engine = AccountingEngine

    cash = db.query(models.ChartAccount).filter_by(company_id=company.id, code="1111").first()

    with pytest.raises(HTTPException, match="غير موجود ضمن هذه الشركة"):
        engine.create_entry(
            db=db,
            company_id=company.id,
            user_id=None,
            description="Bad ref",
            items=[
                {"account_id": cash.id, "debit": Decimal("1000"), "credit": Decimal("0")},
                {"account_id": 9999, "debit": Decimal("0"), "credit": Decimal("1000")},
            ],
            reference="JE-003",
            date="2026-01-15",
        )


def test_trial_balance_sums_to_zero(db, company):
    """Trial balance must net to zero for double-entry system."""
    seed_default_coa(db, company.id)
    engine = AccountingEngine

    cash = db.query(models.ChartAccount).filter_by(company_id=company.id, code="1111").first()
    capital = db.query(models.ChartAccount).filter_by(company_id=company.id, code="3100").first()
    revenue = db.query(models.ChartAccount).filter_by(company_id=company.id, code="4101").first()

    engine.create_entry(
        db=db,
        company_id=company.id,
        user_id=None,
        description="Invest cash",
        items=[
            {"account_id": cash.id, "debit": Decimal("5000"), "credit": Decimal("0")},
            {"account_id": capital.id, "debit": Decimal("0"), "credit": Decimal("5000")},
        ],
        reference="JE-1",
        date="2026-01-01",
    )
    engine.create_entry(
        db=db,
        company_id=company.id,
        user_id=None,
        description="Sell for cash",
        items=[
            {"account_id": cash.id, "debit": Decimal("2000"), "credit": Decimal("0")},
            {"account_id": revenue.id, "debit": Decimal("0"), "credit": Decimal("2000")},
        ],
        reference="JE-2",
        date="2026-01-05",
    )

    accounts = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company.id).all()
    # توازن مزدوج: مجموع أرصدة الطبيعة المدينة (أصول/مصروفات) = مجموع أرصدة الطبيعة الدائنة
    # (خصوم/حقوق ملكية/إيرادات) — اصطلاح المنتج: كل رصيد يُخزن بموجب اتجاهه الطبيعي.
    total_debit = sum(a.balance for a in accounts if a.type in ("asset", "expense"))
    total_credit = sum(a.balance for a in accounts if a.type in ("liability", "equity", "revenue"))

    assert total_debit == total_credit
