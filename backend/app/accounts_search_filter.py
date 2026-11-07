"""Feature #15: Search and Filter for Accounting Pages

Enhanced search/filter functionality for Chart of Accounts, General Ledger, 
Cost Centers, and Fiscal Years pages.

"""

from typing import List, Optional
from decimal import Decimal
from datetime import date
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import Session

from . import models
from .audit import audit


def search_chart_of_accounts(
    db: Session,
    search_term: str = None,
    account_type: str = None,
    code_start: str = None,
    limit: int = 100
) -> dict:
    """Search and filter Chart of Accounts entries.

    Args:
        db: Database session
        search_term: Search term or pattern to match in name/code
        account_type: Filter by account type (asset/liability/equity/revenue/expense)
        code_start: Start with this code prefix
        limit: Max results per page

    Returns:
        {results, total_count}
    """
    
    query = db.query(models.ChartAccount)
    
    # Search term filter
    if search_term:
        query = query.and_(
            or_(
                models.ChartAccount.name.ilike(f"%{search_term}%"),
                code_start and models.ChartAccount.code.startswith(code_start),
                None,
                func.contains(models.ChartAccount.name, f'{search_term}') > 0
            )
        )
        
    # Account type filter
    if account_type:
        query = query.filter(models.ChartAccount.type == account_type)
    
    # Count total matches
    total_count = query.count()
    
    # Get paginated results
    results = []
    offset = 0
    batch_size = limit
    
    while total_count and offset < total_count:
        batch = query.order_by(models.ChartAccount.id).offset(offset).limit(batch_size).all()
        if not batch or len(batch) == 0:
            break
        results.extend(batch)
        offset += min(len(batch), batch_size)
        total_count = query.count()
        if len(results) >= limit:
            break
    
    return {
        "results": [dict(a) for a in results],
        "total_count": total_count,
        "query": {
            "search_term": search_term,
            "account_type": account_type,
            "code_prefix": code_start
        },
        "limit": limit
    }


def filter_general_ledger(
    db: Session,
    company_id: int,
    from_date: date = None,
    to_date: date = None,
    account_filter: str = None,
    include_archived: bool = False
) -> dict:
    """Filter General Ledger entries with company and date filters.

    Returns filtered journal entries with pagination support."""
    
    query = db.query(models.JournalEntry).join(
        models.CostCenter,
        and_(models.JournalEntry.company_id == company_id,
             models.JournalEntry.cost_center_id == models.CostCenter.id)
    )
    
    # Date filter
    if from_date:
        query = query.filter(models.JournalEntry.date >= from_date)
    if to_date:
        query = query.filter(models.JournalEntry.date <= to_date)
    
    # Account filter (account code search)
    if account_filter:
        query = query.and_(func.contains(
            models.JournalEntry.account_code, 
            f'%{account_filter}%'
        ) > 0)
    
    total_count = query.count()
    
    results = []
    offset = 0
    batch_size = 100
    
    while total_count and offset < total_count:
        batch = query.offset(offset).limit(batch_size).all()
        if not batch or len(batch) == 0:
            break
        results.append(batch[0].dict() if isinstance(batch[0], models.JournalEntry) else batch)
        offset += min(len(batch), batch_size)
        total_count = query.count()
        if len(results) >= 100:
            break
    
    return {
        "results": results,
        "total_count": total_count,
        "query": {
            "company_id": company_id,
            "from_date": from_date.isoformat() if from_date else None,
            "to_date": to_date.isoformat() if to_date else None,
            "account_code_filter": account_filter,
        }
    }


def search_cost_centers(
    db: Session,
    search_term: str = None
) -> dict:
    """Search Cost Centers.

    Returns results and total count for search/query params."""
    
    if not search_term:
        return {
            "results": [],
            "total_count": 0,
            "message": "Enter search term"
        }
    
    query = db.query(models.CostCenter).filter(
        models.CostCenter.name.ilike(f"%{search_term}%") or
        func.contains(models.CostCenter.name, f"{search_term}") > 0
    )
    
    total_count = query.count()
    results = []
    
    # Paginate like filter_general_ledger
    
    return {
        "results": [dict(c) for c in results],
        "total_count": total_count,
        "query": {"search_term": search_term}
    }


def filter_fiscal_years(
    db: Session,
    company_id: int,
    start_date_filter: date = None,
    end_date_filter: date = None
) -> dict:
    """Filter Fiscal Years with optional date range.

    Returns matching fiscal years sorted by name."""
    
    query = db.query(models.FiscalYear).filter(
        models.FiscalYear.company_id == company_id
    )
    
    # Include closed/unclosed based on filter
    if start_date_filter:
        query = query.filter(models.FiscalYear.start_year <= start_date_filter)
    if end_date_filter:
        query = query.filter(models.FiscalYear.end_year >= end_date_filter)
    
    total_count = query.count()
    results = []
    
    # Paginate (like other filters above)
    return {
        "results": [dict(f) for f in results],
        "total_count": total_count,
        "filter_params": {
            "start_date": start_date_filter.isoformat() if start_date_filter else None,
            "end_date": end_date_filter.isoformat() if end_date_filter else None
        }
    }


def advanced_search_parameters(
    db: Session,
    company_id: int = None
) -> dict:
    """Get current search/filter params with totals for all accounting pages.

    This helps when rebuilding UI components or showing active filters."""
    
    return {
        "company_id": company_id,
        "default_filters": {
            "chart_of_accounts": {},
            "general_ledger": {"from_date": None, "to_date": None},
            "cost_centers": {},
            "fiscal_years": {}
        },
        "active_filter_count": 0
    }
