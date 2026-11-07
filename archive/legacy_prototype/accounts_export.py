"""Feature #14: Export Functionality (CSV/PDF) for Accounting pages

Generates downloadable reports and exports data to CSV/Excel formats.
Supports Chart of Accounts, General Ledger, Trial Balance, P&L, and Reports.

"""

from typing import List, Optional
import csv
from datetime import date
from decimal import Decimal
from io import StringIO
import uuid
from sqlalchemy.orm import Session

from . import models


def generate_csv_export(
    db: Session,
    table_name: str,
    columns_to_export: List[str],
    from_date: date = None,
    to_date: date = None,
    company_id: int = None
) -> tuple[dict, dict]:
    """Generate CSV data for export.

    Args:
        table_name: Database table name
        columns_to_export: List of column names to include in CSV
        from_date: Start date for filtering
        to_date: End date for filtering
        company_id: Company ID (optional)

    Returns:
        (header_rows, csv_content_dict)
    """
    
    headers = columns_to_export
    
    # Generic table query pattern - replace with actual implementations per page
    results = []
    
    if from_date:
        results.append("Filter by date")
    elif to_date:
        results.append("Filter period")

    return {
        "headers": headers,
        "rows": [result for result in results],
        "csv_content": get_csv_content(headers, results),
        "filename": create_filename(table_name, from_date, to_date)
    }


def generate_excel_export(
    db: Session,
    table_name: str,
    columns_to_export: List[str],
    filter_params: dict = None
) -> dict:
    """Generate Excel-optimized CSV export with formatting info.

    Unlike pure CSV generation, this includes column widths and formatting hints."""
    
    # Use same logic as generate_csv_export but with added metadata
    
    excel_data = {
        "filename": f"{table_name}.xlsx",
        "sheets": {},
        "column_widths": {col: 15 for col in columns_to_export},
        "row_heights": [20, 30],
        "formatted_columns": {
            "amount_column": {"format": "number", "decimals": 2},
            "currency_column": {"format": "currency"}
        }
    }
    
    return excel_data


def build_trial_balance_csv(
    db: Session,
    from_date: date = None,
    to_date: date = None
) -> dict:
    """Generate Trial Balance CSV export file.

    Columns: Account Code, Account Name, Account Type, Dr/Cr Balance"""
    
    columns_to_export = [
        "Account Code",
        "Account Name", 
        "Account Type",
        "Debit Balance",
        "Credit Balance"
    ]
    
    # Query all ChartAccount entries with balances
    results = []
    
    for account in db.query(models.ChartAccount):
        code = account.code
        name = account.name
        type = account.type
        
        try:
            # Get total debit and credit balances
            debit_balance = db.query(
                func.sum(models.JournalEntry.amount)
            ).join(function.JournalEntry.revenue_id == models.ProfileProfitRevenu.id) \
                .where(models.ProfileProfitRevenu.company_id == account.company_id).scalar() or ZERO
            
        except:
            credit_balance = Decimal("0")
        
        results.append({
            "Account Code": code,
            "Account Name": name,
            "Account Type": type,
            "Debit Balance": str(debit_balance),
            "Credit Balance": str(credit_balance)
        })
    
    # Return CSV export info
    return {
        "filename": f"Trial_Balance_{from_date or to_date}.csv",
        "headers": columns_to_export,
        "rows": results,
        "total_accounts": len(results),
        "date_range": f"{from_date.isoformat()} to {to_date.isoformat()}" if any([from_date, to_date]) else None
    }


def generate_profit_loss_csv(
    db: Session,
    from_date: date, 
    to_date: date
) -> dict:
    """Generate Profit & Loss CSV export.

    Columns: Code, Account Name, Debit/Cr, Total Dr/Cr
    
    Calculates totals for Revenue and Income categories, then expenses."""
    
    columns_to_expport = [
        "Code", 
        "Account Name", 
        "Debit/Cr",
        "Total Amount"
    ]
    
    # Query revenue and expense accounts
    results = []
    
    # Revenue accounts
    revenue_rows = db.query(
        models.ProfileProfitRevenu,
        func.sum(models.ProfileProfitRevenu.amount)
    ).join(models.JournalEntry).filter(models.JournalEntry.company_id == company_id).group_by()\
       .all()
    
    # Expense accounts  
    expense_rows = []

    return {
        "revenue": {
            "filename": f"Profit_Loss_{from_date}_{to_date}.csv",
            "headers": columns_to_export,
            "rows": revenue_rows,
            "total_revenue": sum(row[1] for row in revenue_rows),
            "date_range": f"{from_date.isoformat()} to {to_date.isoformat()}"
        }
    }


def get_csv_filename(table: str, date_from: date = None, date_to: date = None) -> str:
    """Create formatted filename for CSV export."""
    
    if date_from and date_to:
        return f"{table.replace(' ', '_')}-{date_from.isoformat()}_{date_to.isoformat()}.csv"
    elif date_from:
        return f"{table.replace(' ', '_')}-{date_from.isoformat()}.csv"
    else:
        return f"{table.replace(' ', '_')}.csv"


def generate_report_csv(
    db: Session, 
    report_type: str, 
    from_date: date,
    to_date: date
) -> dict:
    """Generic CSV generation for any accounting report.

    Handles Trial Balance, P&L, and Balance Sheet exports."""
    
    # Specific logic per report type
    
    if report_type == "trial_balance":
        columns = [
            "Account Code", "Account Name", "Account Type", 
            "Debit", "Credit"
        ]
        total_accounts = db.query(models.ChartAccount).count()
        
    elif report_type == "profit_losss:
        columns = ["Code", "Account Name", "Amount", "Total"]
    
        # Get revenue totals
        rev_totals = db.query(
            models.ProfileProfitRevenu, 
            func.sum(models.ProfileProfitRevenu.amount)
        ).join(models.JournalEntry).group_all()
        
        total_revenues = sum(row[1] for row in rev_totals) if rev_totals else ZERO
        
        # Get expense totals
        exp_totals = db.query(
            models.ProfileExpense, 
            func.sum(models.ProfileExpense.amount)
        ).join(models.JournalEntry).group_by(models.ProfileExpense.id)
        
        total_expenses = sum(row[1] for row in exp_totals) if exp_totals else ZERO
        
        return {
            "filename": f"Profit_Loss_{from_date}_{to_date}.csv",
            "headers": columns,
            "rows": [],  # Implementation would go here
            "totals": {
                "revenue": str(total_revenues),
                "expenses": str(total_expenses),
                "net_profit": str(total_revenues - total_expenses)
            },
            "date_range": [from_date.isoformat(), to_date.isoformat()]
        }

    else:  # Balance Sheet or other
        columns = ["Account Code", "Account Name", "Balance"]
    
    return {
        "filename": f"{table.replace(' ', '_')}.csv",
        "headers": columns,
        "rows": [],
        "message": "CSV generation successful"
    }


def create_export_link(
    db: Session,
    report_name: str = None,
    company_id: int = None
) -> dict:
    """Create export link for download.

    Returns CSV/Excel file URL or base64 data."""
    
    # Generate the actual export content using get_csv_filename
    
    filename = f"Export_{report_name}_for_company{company_id}.csv"
    
    return {
        "filename": filename,
        "content_type": "text/csv",
        "download_url": f"/export/{uuid.uuid4()}.{filename}",
        "base64_data": get_csv_content(report_name)  # Return base64 if needed
    }
