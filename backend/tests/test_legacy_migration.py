"""Verify data-preserving upgrade from the last pre-tenancy PostgreSQL revision."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


BACKEND_DIR = Path(__file__).resolve().parents[1]
TENANT_TABLES = (
    "warehouses",
    "suppliers",
    "products",
    "customers",
    "purchase_orders",
    "purchase_order_items",
    "sales_orders",
    "sales_order_items",
    "stock_movements",
    "payments",
    "audit_logs",
    "sales_returns",
    "sales_return_items",
    "purchase_returns",
    "purchase_return_items",
    "shifts",
    "stocktakes",
    "stocktake_lines",
)


def _run_migration(database_url: str, revision: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=BACKEND_DIR,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(
            f"Alembic upgrade to {revision} failed:\n{result.stdout}\n{result.stderr}"
        )


def _insert_id(connection, statement: str, parameters: dict) -> int:
    return connection.execute(text(statement), parameters).scalar_one()


def _seed_legacy_data(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            user_id = _insert_id(
                connection,
                "INSERT INTO users (username, hashed_password, role) "
                "VALUES (:username, :password, 'admin') RETURNING id",
                {"username": "legacy-admin", "password": "not-a-real-password-hash"},
            )
            warehouse_id = _insert_id(
                connection,
                "INSERT INTO warehouses (name, code) VALUES ('Legacy warehouse', 'legacy') "
                "RETURNING id",
                {},
            )
            supplier_id = _insert_id(
                connection,
                "INSERT INTO suppliers (name) VALUES ('Legacy supplier') RETURNING id",
                {},
            )
            customer_id = _insert_id(
                connection,
                "INSERT INTO customers (name) VALUES ('Legacy customer') RETURNING id",
                {},
            )
            product_id = _insert_id(
                connection,
                "INSERT INTO products (sku, name, quantity, warehouse_id, supplier_id) "
                "VALUES ('LEGACY-SKU', 'Legacy product', 25, :warehouse_id, :supplier_id) "
                "RETURNING id",
                {"warehouse_id": warehouse_id, "supplier_id": supplier_id},
            )
            purchase_order_id = _insert_id(
                connection,
                "INSERT INTO purchase_orders (supplier_id, warehouse_id, status, total_amount) "
                "VALUES (:supplier_id, :warehouse_id, 'received', 12.50) RETURNING id",
                {"supplier_id": supplier_id, "warehouse_id": warehouse_id},
            )
            purchase_item_id = _insert_id(
                connection,
                "INSERT INTO purchase_order_items (order_id, product_id, quantity, unit_cost) "
                "VALUES (:order_id, :product_id, 1, 12.50) RETURNING id",
                {"order_id": purchase_order_id, "product_id": product_id},
            )
            sales_order_id = _insert_id(
                connection,
                "INSERT INTO sales_orders (customer_id, warehouse_id, status, total_amount) "
                "VALUES (:customer_id, :warehouse_id, 'confirmed', 20.00) RETURNING id",
                {"customer_id": customer_id, "warehouse_id": warehouse_id},
            )
            sales_item_id = _insert_id(
                connection,
                "INSERT INTO sales_order_items (order_id, product_id, quantity, unit_price) "
                "VALUES (:order_id, :product_id, 1, 20.00) RETURNING id",
                {"order_id": sales_order_id, "product_id": product_id},
            )
            connection.execute(
                text(
                    "INSERT INTO stock_movements (product_id, warehouse_id, change, reason) "
                    "VALUES (:product_id, :warehouse_id, 25, 'adjustment')"
                ),
                {"product_id": product_id, "warehouse_id": warehouse_id},
            )
            connection.execute(
                text("INSERT INTO payments (customer_id, amount) VALUES (:customer_id, 2.50)"),
                {"customer_id": customer_id},
            )
            connection.execute(
                text(
                    "INSERT INTO audit_logs (user_id, username, action, entity) "
                    "VALUES (:user_id, 'legacy-admin', 'create', 'product')"
                ),
                {"user_id": user_id},
            )
            sales_return_id = _insert_id(
                connection,
                "INSERT INTO sales_returns "
                "(order_id, customer_id, warehouse_id, total_amount) "
                "VALUES (:order_id, :customer_id, :warehouse_id, 1.00) RETURNING id",
                {
                    "order_id": sales_order_id,
                    "customer_id": customer_id,
                    "warehouse_id": warehouse_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO sales_return_items "
                    "(return_id, order_item_id, product_id, quantity, unit_price) "
                    "VALUES (:return_id, :item_id, :product_id, 1, 20.00)"
                ),
                {
                    "return_id": sales_return_id,
                    "item_id": sales_item_id,
                    "product_id": product_id,
                },
            )
            purchase_return_id = _insert_id(
                connection,
                "INSERT INTO purchase_returns "
                "(order_id, supplier_id, warehouse_id, total_amount) "
                "VALUES (:order_id, :supplier_id, :warehouse_id, 1.00) RETURNING id",
                {
                    "order_id": purchase_order_id,
                    "supplier_id": supplier_id,
                    "warehouse_id": warehouse_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO purchase_return_items "
                    "(return_id, order_item_id, product_id, quantity, unit_price) "
                    "VALUES (:return_id, :item_id, :product_id, 1, 12.50)"
                ),
                {
                    "return_id": purchase_return_id,
                    "item_id": purchase_item_id,
                    "product_id": product_id,
                },
            )
            connection.execute(
                text("INSERT INTO shifts (user_id, username) VALUES (:user_id, 'legacy-admin')"),
                {"user_id": user_id},
            )
            stocktake_id = _insert_id(
                connection,
                "INSERT INTO stocktakes (warehouse_id, created_by, username) "
                "VALUES (:warehouse_id, :user_id, 'legacy-admin') RETURNING id",
                {"warehouse_id": warehouse_id, "user_id": user_id},
            )
            connection.execute(
                text(
                    "INSERT INTO stocktake_lines "
                    "(stocktake_id, product_id, system_qty) VALUES (:stocktake_id, :product_id, 25)"
                ),
                {"stocktake_id": stocktake_id, "product_id": product_id},
            )
    finally:
        engine.dispose()


def _verify_tenant_ownership(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            company_id = connection.execute(
                text("SELECT id FROM companies WHERE code = 'default'")
            ).scalar_one()
            assert connection.execute(
                text(
                    "SELECT role FROM user_company_memberships "
                    "WHERE user_id = (SELECT id FROM users WHERE username = 'legacy-admin') "
                    "AND company_id = :company_id"
                ),
                {"company_id": company_id},
            ).scalar_one() == "admin"
            assert connection.execute(
                text("SELECT is_platform_admin FROM users WHERE username = 'legacy-admin'")
            ).scalar_one() is True

            for table in TENANT_TABLES:
                count = connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE company_id = :company_id"),
                    {"company_id": company_id},
                ).scalar_one()
                assert count == 1, f"{table}: expected its legacy row to belong to default company"

            product = connection.execute(
                text(
                    "SELECT sku, quantity, company_id FROM products "
                    "WHERE sku = 'LEGACY-SKU'"
                )
            ).one()
            assert (product.sku, product.quantity, product.company_id) == (
                "LEGACY-SKU",
                25,
                company_id,
            )
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "0011"
    finally:
        engine.dispose()


def main() -> None:
    base_url = os.environ.get("DATABASE_URL")
    if not base_url:
        raise RuntimeError("DATABASE_URL must point to a disposable PostgreSQL database")
    url = make_url(base_url)
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("Legacy migration verification requires PostgreSQL")

    schema = f"migration_check_{uuid.uuid4().hex}"
    admin_engine = create_engine(base_url)
    try:
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')

        isolated_url = url.update_query_dict(
            {"options": f"-csearch_path={schema}"}
        ).render_as_string(hide_password=False)
        _run_migration(isolated_url, "0008")
        _seed_legacy_data(isolated_url)
        _run_migration(isolated_url, "head")
        _verify_tenant_ownership(isolated_url)
        print("Legacy PostgreSQL data upgrade from 0008 to head preserved all seeded records.")
    finally:
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin_engine.dispose()


if __name__ == "__main__":
    main()


def test_populated_legacy_postgresql_upgrade() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        pytest.skip("This migration integration test runs in PostgreSQL CI.")
    main()
