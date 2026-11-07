from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


MIGRATION_PATH = Path(__file__).parents[1] / "alembic" / "versions" / "f3b7a2c9d4e1_safes_branch.py"


def test_safe_branch_migration_backfills_existing_safes_and_creates_missing_branches():
    spec = spec_from_file_location("safe_branch_migration", MIGRATION_PATH)
    migration = module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE companies (id INTEGER PRIMARY KEY, code VARCHAR(50))"))
        connection.execute(text("CREATE TABLE branches (id INTEGER PRIMARY KEY, company_id INTEGER, name VARCHAR(150), code VARCHAR(50), is_active BOOLEAN, created_at DATETIME, updated_at DATETIME)"))
        connection.execute(text("CREATE TABLE safes (id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, name VARCHAR(150), code VARCHAR(50), balance NUMERIC, is_active BOOLEAN, created_at DATETIME)"))
        connection.execute(text("INSERT INTO companies (id, code) VALUES (1, 'one'), (2, 'two')"))
        connection.execute(text("INSERT INTO branches (id, company_id, name, code, is_active) VALUES (10, 1, 'Existing branch', 'existing', 1)"))
        connection.execute(text("INSERT INTO safes (id, company_id, name, code, balance, is_active) VALUES (20, 1, 'Till', 'safe-1', 0, 1), (21, 2, 'Cash', 'safe-2', 0, 1)"))

        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        rows = connection.execute(text("SELECT id, branch_id FROM safes ORDER BY id")).all()
        assert rows[0] == (20, 10)
        assert rows[1][1] is not None
        assert connection.execute(text("SELECT count(*) FROM branches WHERE company_id=2")).scalar_one() == 1

    engine.dispose()
