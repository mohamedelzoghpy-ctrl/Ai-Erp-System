import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.database import Base
from app.routers.masterdata import _default_branch_id


def test_default_branch_is_created_once_for_legacy_warehouse_api():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    with Session(engine) as db:
        first_branch_id = _default_branch_id(db)
        second_branch_id = _default_branch_id(db)

        assert first_branch_id == second_branch_id
        assert db.query(models.Company).count() == 1
        assert db.query(models.Branch).count() == 1

    engine.dispose()


def test_users_belong_to_one_company_and_can_have_branch_and_warehouse_access():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    with Session(engine) as db:
        company = models.Company(name="First Company", code="first")
        user = models.User(username="admin", hashed_password="hash", role="admin")
        db.add_all([company, user])
        db.flush()
        db.info["company_id"] = company.id

        branch = models.Branch(company_id=company.id, name="Main", code="main")
        db.add(branch)
        db.flush()
        warehouse = models.Warehouse(name="Main", code="main", branch_id=branch.id)
        db.add(warehouse)
        db.flush()
        db.add(
            models.UserCompanyMembership(
                user_id=user.id,
                company_id=company.id,
                role="staff",
            )
        )
        db.add(models.UserBranchAccess(user_id=user.id, branch_id=branch.id))
        db.add(models.UserWarehouseAccess(user_id=user.id, warehouse_id=warehouse.id))
        db.commit()

        assert len(user.memberships) == 1
        assert user.memberships[0].company.code == "first"
        assert user.memberships[0].role == "staff"
        assert [access.branch.code for access in user.branch_access] == ["main"]
        assert [access.warehouse.code for access in user.warehouse_access] == ["main"]

        another_company = models.Company(name="Second Company", code="second")
        db.add(another_company)
        db.flush()
        db.add(models.UserCompanyMembership(user_id=user.id, company_id=another_company.id, role="staff"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    engine.dispose()


def test_orm_queries_are_scoped_to_company_and_employee_resource_grants():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    with Session(engine) as db:
        first = models.Company(name="First", code="first")
        second = models.Company(name="Second", code="second")
        db.add_all([first, second])
        db.flush()
        first_branch = models.Branch(company_id=first.id, name="First", code="first")
        second_branch = models.Branch(company_id=second.id, name="Second", code="second")
        db.add_all([first_branch, second_branch])
        db.flush()
        first_warehouse = models.Warehouse(
            company_id=first.id, branch_id=first_branch.id, name="First", code="first"
        )
        second_warehouse = models.Warehouse(
            company_id=second.id, branch_id=second_branch.id, name="Second", code="second"
        )
        db.add_all([first_warehouse, second_warehouse])
        db.flush()
        db.add_all(
            [
                models.Product(company_id=first.id, sku="SKU", name="First product", warehouse_id=first_warehouse.id),
                models.Product(company_id=second.id, sku="SKU", name="Second product", warehouse_id=second_warehouse.id),
            ]
        )
        db.commit()
        first_company_id = first.id
        first_branch_id = first_branch.id
        first_warehouse_id = first_warehouse.id

    with Session(engine) as db:
        db.info.update(
            company_id=first_company_id,
            company_role="staff",
            branch_ids=(first_branch_id,),
            visible_branch_ids=(first_branch_id,),
            warehouse_ids=(first_warehouse_id,),
        )

        assert [w.code for w in db.query(models.Warehouse).all()] == ["first"]
        assert [p.name for p in db.query(models.Product).all()] == ["First product"]
        assert [b.code for b in db.query(models.Branch).all()] == ["first"]

    engine.dispose()
