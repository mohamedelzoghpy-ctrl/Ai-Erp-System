"""Deterministic, collision-resistant identifiers generated from entity names."""

import re
import unicodedata

from sqlalchemy.orm import Session


def slug_code(name: str, fallback: str = "item", max_length: int = 40) -> str:
    """Create an ASCII code from Arabic, Latin, or mixed-language names."""
    raw = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^a-zA-Z0-9]+", "-", raw.lower()).strip("-")
    return (base or fallback)[:max_length].rstrip("-") or fallback


def _code_exists(db: Session, model, company_id: int | None, field: str, candidate: str) -> bool:
    query = db.query(model.id).filter(getattr(model, field) == candidate)
    if company_id is not None and hasattr(model, "company_id"):
        query = query.filter(model.company_id == company_id)
    return query.first() is not None


def unique_code(db: Session, model, company_id: int | None, name: str, prefix: str, max_length: int = 50) -> str:
    """Generate a unique company-scoped code, checking existing rows before insert."""
    base = slug_code(name, fallback=prefix.lower(), max_length=max_length - 6)
    candidate = f"{prefix}-{base}"[:max_length]
    suffix = 2
    while _code_exists(db, model, company_id, "code", candidate):
        tail = f"-{suffix}"
        candidate = f"{prefix}-{base[:max_length - len(prefix) - len(tail) - 1]}{tail}"
        suffix += 1
    return candidate


def unique_sku(db: Session, model, company_id: int | None, name: str, max_length: int = 60) -> str:
    """Generate a unique product SKU from the product name."""
    base = slug_code(name, fallback="product", max_length=max_length - 5).upper()
    candidate = f"SKU-{base}"[:max_length]
    suffix = 2
    while _code_exists(db, model, company_id, "sku", candidate):
        tail = f"-{suffix}"
        candidate = f"SKU-{base[:max_length - 4 - len(tail)]}{tail}"
        suffix += 1
    return candidate
