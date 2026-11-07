from typing import List, Optional
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import func
from . import models, schemas
from .audit import audit
from .codegen import unique_code


def seed_default_cost_centers(db, company_id: int) -> int:
    existing = db.query(models.CostCenter).filter(models.CostCenter.company_id == company_id).count()
    if existing:
        return 0
    cc = models.CostCenter(company_id=company_id, code="CC-GEN", name="عام (General)", is_active=True)
    db.add(cc)
    db.flush()
    db.commit()
    return 1


def seed_default_fiscal_year(db, company_id: int) -> int:
    existing = db.query(models.FiscalYear).filter(models.FiscalYear.company_id == company_id).count()
    if existing:
        return 0
    from datetime import date
    today = date.today()
    fy = models.FiscalYear(
        company_id=company_id,
        name=f"FY {today.year}",
        start_date=date(today.year, 1, 1),
        end_date=date(today.year, 12, 31),
        is_closed=False,
    )
    db.add(fy)
    db.flush()
    db.commit()
    return 1


def ensure_company_coa(db, company_id: int) -> None:
    """Seed the default CoA for a company if it has none (lazy)."""
    if company_id is None:
        return
    seed_default_coa(db, company_id)


def link_safe_coa(db, safe: "models.Safe", company_id: int) -> None:
    if safe.chart_account_id:
        return
    seed_default_coa(db, company_id)
    parent = db.query(models.ChartAccount).filter(
        models.ChartAccount.company_id == company_id, models.ChartAccount.code.in_(("1011", "1111"))
    ).order_by(models.ChartAccount.code).first()
    if parent is None:
        return
    acc = models.ChartAccount(
        company_id=company_id,
        code=unique_code(db, models.ChartAccount, company_id, safe.name, "CASH", max_length=50),
        name=f"Safe: {safe.name}",
        type="asset",
        parent_id=parent.id,
        is_group=False,
        balance=safe.balance or 0,
        is_active=safe.is_active,
    )
    db.add(acc)
    db.flush()
    safe.chart_account_id = acc.id


def link_bank_coa(db, bank: "models.Bank", company_id: int) -> None:
    if bank.chart_account_id:
        return
    seed_default_coa(db, company_id)
    parent = db.query(models.ChartAccount).filter(
        models.ChartAccount.company_id == company_id, models.ChartAccount.code.in_(("1010", "1112"))
    ).order_by(models.ChartAccount.code.desc()).first()
    if parent is None:
        return
    acc = models.ChartAccount(
        company_id=company_id,
        code=unique_code(db, models.ChartAccount, company_id, bank.name, "BANK", max_length=50),
        name=f"Bank: {bank.name}",
        type="asset",
        parent_id=parent.id,
        is_group=False,
        balance=bank.balance or 0,
        is_active=bank.is_active,
    )
    db.add(acc)
    db.flush()
    bank.chart_account_id = acc.id


def link_party_coa(db, party: "models.Supplier | models.Customer", company_id: int, is_customer: bool) -> None:
    if party.chart_account_id:
        return
    seed_default_coa(db, company_id)
    code = "1100" if is_customer else "2100"
    acc = db.query(models.ChartAccount).filter(
        models.ChartAccount.company_id == company_id, models.ChartAccount.code == code
    ).first()
    if acc is not None:
        party.chart_account_id = acc.id

class AccountingEngine:
    """
    Core accounting logic for MOZAD ERP.
    Handles double-entry journal entries and balance roll-ups.
    """

    @staticmethod
    def create_entry(
        db: Session,
        company_id: int,
        user_id: Optional[int],
        description: str,
        items: List[dict],
        reference: Optional[str] = None,
        date = None
    ):
        """
        Creates a balanced journal entry and updates the balances of the affected accounts.
        items: List of { "account_id": int, "debit": Decimal, "credit": Decimal, "cost_center_id": int, "notes": str }
        """
        # Validate balance up front
        total_debit = sum((item.get("debit", Decimal("0")) for item in items), Decimal("0"))
        total_credit = sum((item.get("credit", Decimal("0")) for item in items), Decimal("0"))
        if total_debit != total_credit:
            raise ValueError(f"Journal entry must balance. Debit ({total_debit}) != Credit ({total_credit})")

        # 1. Create the Journal Entry
        db_entry = models.JournalEntry(
            company_id=company_id,
            created_by=user_id,
            description=description,
            reference=reference,
            date=date or models.func.current_date()
        )
        db.add(db_entry)
        db.flush() # Get entry.id

        # 2. Create Journal Items and update account balances
        for item in items:
            db_item = models.JournalItem(
                entry_id=db_entry.id,
                company_id=company_id,
                account_id=item["account_id"],
                debit=item.get("debit", Decimal("0")),
                credit=item.get("credit", Decimal("0")),
                cost_center_id=item.get("cost_center_id"),
                notes=item.get("notes"),
            )
            db.add(db_item)

            # Update the account balance
            # For Assets/Expenses: Debit increases balance, Credit decreases it.
            # For Liabilities/Equity/Revenue: Credit increases balance, Debit decreases it.
            acc = db.query(models.ChartAccount).get(item["account_id"])
            if not acc:
                raise ValueError(f"Account {item['account_id']} not found")

            delta = item.get("debit", Decimal("0")) - item.get("credit", Decimal("0"))

            if acc.type in ("liability", "equity", "revenue"):
                acc.balance -= delta
            else:
                acc.balance += delta

        db.flush()
        return db_entry

    @staticmethod
    def roll_up_balances(db: Session, company_id: int):
        """
        Recursively updates the balances of group accounts based on their children.
        This should be called after major updates or as a scheduled task.
        """
        # We fetch all accounts for the company
        accounts = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id).all()

        # Build a map of children for each parent
        children_map = {}
        for acc in accounts:
            if acc.parent_id:
                children_map.setdefault(acc.parent_id, []).append(acc)

        # Bottom-up update: start with accounts that have no children (leaf nodes)
        # In a real scenario, we would use a recursive function or a topological sort.
        def calculate_balance(acc_id):
            acc = db.query(models.ChartAccount).get(acc_id)
            children = children_map.get(acc_id, [])

            if not children:
                # Leaf account: balance is already correct from JournalItems
                return acc.balance

            # Group account: balance is sum of children balances
            total = Decimal("0")
            for child in children:
                total += calculate_balance(child.id)

            acc.balance = total
            return total

        # Update all root accounts (those without parents)
        roots = [a for a in accounts if a.parent_id is None]
        for root in roots:
            calculate_balance(root.id)

        db.commit()


def seed_default_coa(db, company_id: int) -> int:
    """Create a standard Chart of Accounts for a company if it has none.

    Returns the number of accounts created (0 if already seeded).
    Idempotent: does nothing when the company already has any ChartAccount.
    """
    spec = [
        # --- Assets ---
        ("1000", "الأصول", "asset", None, True),
        ("1100", "الأصول المتداولة", "asset", "1000", True),
        ("1110", "النقد والبنوك", "asset", "1100", True),
        ("1111", "الصندوق (Cash)", "asset", "1110", False),
        ("1112", "حساب بنكي (Bank)", "asset", "1110", False),
        ("1115", "حافظة الشيكات (Cheques Under Collection)", "asset", "1110", False),
        ("1130", "إنتاج تحت التشغيل (WIP)", "asset", "1100", False),
        ("1120", "ذمم العملاء (Accounts Receivable)", "asset", "1100", False),
        ("1101", "المخزون (Inventory)", "asset", "1100", False),
        ("1140", "مصروفات مدفوعة مقدماً (Prepaid)", "asset", "1100", False),
        ("1200", "الأصول الثابتة", "asset", "1000", True),
        ("1210", "المعدات (Equipment)", "asset", "1200", False),
        ("1220", "المركبات (Vehicles)", "asset", "1200", False),
        ("1230", "الأثاث والتجهيزات", "asset", "1200", False),
        ("1290", "الاستهلاك المتراكم (Accumulated Depreciation)", "asset", "1200", False),
        # --- Liabilities ---
        ("2000", "الخصوم", "liability", None, True),
        ("2100", "الخصوم المتداولة", "liability", "2000", True),
        ("2110", "ذمم الموردين (Accounts Payable)", "liability", "2100", False),
        ("2111", "شيكات مصروفة (Issued Cheques)", "liability", "2100", False),
        ("2120", "مصاريف مستحقة (Accrued Expenses)", "liability", "2100", False),
        ("2130", "ضريبة القيمة المضافة (VAT Payable)", "liability", "2100", False),
        ("2140", "رواتب مستحقة (Salaries Payable)", "liability", "2100", False),
        ("2200", "الخصوم طويلة الأجل", "liability", "2000", True),
        ("2210", "قروض (Loans Payable)", "liability", "2200", False),
        # --- Equity ---
        ("3000", "حقوق الملكية", "equity", None, True),
        ("3100", "رأس المال (Capital)", "equity", "3000", False),
        ("3200", "الأرباح المبقاة (Retained Earnings)", "equity", "3000", False),
        # --- Revenue ---
        ("4000", "الإيرادات", "revenue", None, True),
        ("4100", "إيرادات المبيعات", "revenue", "4000", True),
        ("4101", "إيرادات المبيعات (Sales Revenue)", "revenue", "4100", False),
        ("4200", "إيرادات أخرى", "revenue", "4000", False),
        # --- Expenses ---
        ("5000", "المصاريف", "expense", None, True),
        ("5100", "تكلفة البضاعة المباعة (COGS)", "expense", "5000", False),
        ("5200", "المصاريف التشغيلية", "expense", "5000", True),
        ("5210", "الرواتب والأجور", "expense", "5200", False),
        ("5220", "الإيجار", "expense", "5200", False),
        ("5230", "الخدمات (كهرباء/ماء/انترنت)", "expense", "5200", False),
        ("5240", "الاستهلاك (Depreciation)", "expense", "5200", False),
        ("5250", "التسويق والإعلان", "expense", "5200", False),
        ("5260", "لوازم مكتبية", "expense", "5200", False),
        ("5300", "المصاريف المالية", "expense", "5000", True),
        ("5310", "رسوم بنكية", "expense", "5300", False),
        # --- Additional assets ---
        ("1150", "استثمارات قصيرة الأجل", "asset", "1100", False),
        ("1240", "الأصول غير الملموسة", "asset", "1200", True),
        ("1241", "برمجيات (Software)", "asset", "1240", False),
        ("1242", "براءات/علامات تجارية", "asset", "1240", False),
        ("1291", "الاستهلاك المتراكم (غير ملموس)", "asset", "1240", False),
        # --- Additional liabilities ---
        ("2150", "دفعات مقدمة من العملاء", "liability", "2100", False),
        ("2160", "قروض قصيرة الأجل/ découvert", "liability", "2100", False),
        ("2170", "فوائد مستحقة", "liability", "2100", False),
        ("2220", "الضرائب المؤجلة", "liability", "2200", False),
        # --- Additional equity ---
        ("3300", "سحوبات المالك (Drawings)", "equity", "3000", False),
        # --- Additional revenue ---
        ("4102", "مرتجعات المبيعات (contra)", "revenue", "4100", False),
        ("4210", "إيرادات خدمات", "revenue", "4200", False),
        ("4220", "إيرادات فوائد", "revenue", "4200", False),
        ("4230", "إيرادات أخرى", "revenue", "4200", False),
        # --- Additional expenses ---
        ("5110", "شحن/نقل (Inbound Freight)", "expense", "5100", False),
        ("5270", "التأمين", "expense", "5200", False),
        ("5280", "رسوم مهنية (قانونية/محاسبية)", "expense", "5200", False),
        ("5290", "سفر وضيافة", "expense", "5200", False),
        ("5320", "صيانة وإصلاح", "expense", "5200", False),
        ("5330", "رسوم جمركية", "expense", "5200", False),
        ("5340", "ديون معدومة (Bad Debt)", "expense", "5200", False),
        ("5400", "مصاريف فوائد", "expense", "5300", False),
        ("5500", "ضريبة الدخل", "expense", "5000", False),
        ("5600", "مصاريف متنوعة", "expense", "5000", False),
        # --- Niche/specialized accounts ---
        ("1113", "نقد معادل (Money Market)", "asset", "1110", False),
        ("1114", "نقد مقيد (Restricted Cash)", "asset", "1110", False),
        ("2180", "إيرادات مؤجلة (Deferred Revenue)", "liability", "2100", False),
        ("2190", "مخصص ضمان (Warranty Provision)", "liability", "2100", False),
        ("2191", "مخصص مزايا موظفين (Pension/Gratuity)", "liability", "2100", False),
        ("3500", "فائض إعادة تقييم (Revaluation Surplus)", "equity", "3000", False),
        ("4240", "أرباح صرف (FX Gains)", "revenue", "4200", False),
        ("5350", "خسائر صرف (FX Losses)", "expense", "5300", False),
    ]
    existing_codes = {c[0] for c in db.query(models.ChartAccount.code).filter(models.ChartAccount.company_id == company_id).all()}
    if not any(code not in existing_codes for code, *_ in spec):
        return 0  # every default account already exists (companies may also have custom accounts)

    # (code, name, type, parent_code, is_group)


    by_code = {}
    created = 0
    for code, name, typ, parent_code, is_group in spec:
        if code in existing_codes:
            # reuse existing account for parent linking
            ex = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == code).first()
            if ex is not None:
                by_code[code] = ex
            continue
        parent_id = by_code[parent_code].id if parent_code and parent_code in by_code else None
        # if parent not yet created (existing), look it up
        if parent_id is None and parent_code is not None:
            pacc = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == parent_code).first()
            if pacc is not None:
                parent_id = pacc.id
        acc = models.ChartAccount(
            company_id=company_id,
            code=code,
            name=name,
            type=typ,
            parent_id=parent_id,
            is_group=is_group,
            balance=0,
            is_active=True,
        )
        db.add(acc)
        db.flush()
        by_code[code] = acc
        created += 1

    db.commit()
    return created
