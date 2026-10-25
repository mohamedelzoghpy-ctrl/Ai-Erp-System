from sqlalchemy import create_engine
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
