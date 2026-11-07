from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models
from app.codegen import slug_code, unique_code, unique_sku
from app.database import Base


def test_slug_code_handles_ascii_arabic_and_empty_names():
    assert slug_code("North Branch") == "north-branch"
    assert slug_code("فرع القاهرة", fallback="branch") == "branch"
    assert slug_code("", fallback="store") == "store"


def test_generated_codes_are_unique_within_company_and_reusable_across_companies():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            company_a = models.Company(name="Acme", code="acme")
            company_b = models.Company(name="Other", code="other")
            db.add_all([company_a, company_b])
            db.flush()
            db.info["company_id"] = company_a.id
            db.add(models.Branch(company_id=company_a.id, name="North", code="BR-north"))
            db.add(models.Product(company_id=company_a.id, sku="SKU-NORTH", name="North"))
            db.flush()

            assert unique_code(db, models.Branch, company_a.id, "North", "BR") == "BR-north-2"
            assert unique_sku(db, models.Product, company_a.id, "North") == "SKU-NORTH-2"
            assert unique_code(db, models.Branch, company_b.id, "North", "BR") == "BR-north"
            assert unique_sku(db, models.Product, company_b.id, "North") == "SKU-NORTH"
    finally:
        engine.dispose()


def test_generated_codes_support_global_company_identifier():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            first = models.Company(name="Alpha", code="alpha")
            second = models.Company(name="Beta", code="beta")
            db.add_all([first, second])
            db.flush()
            assert unique_code(db, models.Company, None, "Alpha", "co") == "co-alpha"
            first.code = "co-alpha"
            db.flush()
            assert unique_code(db, models.Company, None, "Alpha", "co") == "co-alpha-2"
    finally:
        engine.dispose()
