from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


def test_platform_company_creation_limits_and_employee_resource_scope():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
                "/auth/setup",
                json={"username": "platform", "password": "long-password", "full_name": "Platform"},
            )
        assert response.status_code == 201, response.text
        for path in (
            "/warehouses",
            "/customers",
            "/products",
            "/sales-orders",
            "/purchase-orders",
            "/payments",
            "/sales-returns",
            "/purchase-returns",
        ):
            response = client.get(path)
            assert response.status_code == 401, f"{path}: {response.text}"

        response = client.post(
            "/auth/login",
            data={"username": "platform", "password": "long-password"},
        )
        assert response.status_code == 200, response.text
        platform_token = response.json()["access_token"]
        platform_headers = {"Authorization": f"Bearer {platform_token}"}

        response = client.post(
                "/platform/companies",
                headers=platform_headers,
                json={
                    "name": "Company One",
                    "code": "one",
                    "max_warehouses_per_branch": 1,
                    "admin_username": "company-admin",
                    "admin_password": "company-password",
                },
            )
        assert response.status_code == 201, response.text
        company_id = response.json()["id"]

        response = client.post(
                "/auth/login",
                data={"username": "company-admin", "password": "company-password"},
            )
        assert response.status_code == 200, response.text
        company_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = client.post(
                "/company/branches",
                headers=company_headers,
                json={"name": "Branch Two", "code": "two"},
            )
        assert response.status_code == 201, response.text
        branch_two_id = response.json()["id"]

        response = client.post(
                "/warehouses",
                headers=company_headers,
                json={"name": "Warehouse One", "code": "one", "branch_id": branch_two_id},
            )
        assert response.status_code == 201, response.text
        warehouse_id = response.json()["id"]

        response = client.post(
                "/warehouses",
                headers=company_headers,
                json={"name": "Warehouse Two", "code": "two", "branch_id": branch_two_id},
            )
        assert response.status_code == 409, response.text
        response = client.post(
            "/company/branches",
            headers=company_headers,
            json={"name": "Branch Three", "code": "three"},
        )
        assert response.status_code == 201, response.text
        branch_three_id = response.json()["id"]
        response = client.post(
            "/warehouses",
            headers=company_headers,
            json={"name": "Warehouse Three", "code": "three", "branch_id": branch_three_id},
        )
        assert response.status_code == 201, response.text
        warehouse_three_id = response.json()["id"]

        response = client.post(
                "/company/employees",
                headers=company_headers,
                json={
                    "username": "branch-staff",
                    "password": "staff-password",
                    "role": "staff",
                    "branch_ids": [branch_three_id],
                    "warehouse_ids": [warehouse_id],
                },
            )
        assert response.status_code == 201, response.text
        assert response.json()["branch_ids"] == [branch_three_id]
        assert response.json()["warehouse_ids"] == [warehouse_id]

        response = client.post(
            "/auth/users",
            headers=company_headers,
            json={
                "username": "unscoped-staff",
                "password": "staff-password",
                "role": "staff",
            },
        )
        assert response.status_code == 422, response.text

        response = client.post(
            "/auth/users",
            headers=company_headers,
            json={
                "username": "legacy-route-staff",
                "password": "staff-password",
                "role": "staff",
                "branch_ids": [branch_three_id],
            },
        )
        assert response.status_code == 201, response.text

        response = client.post(
            "/auth/login",
            data={"username": "legacy-route-staff", "password": "staff-password"},
        )
        assert response.status_code == 200, response.text
        legacy_staff_headers = {"Authorization": "Bearer " + response.json()["access_token"]}
        response = client.get("/company/branches", headers=legacy_staff_headers)
        assert response.status_code == 200, response.text
        assert [branch["id"] for branch in response.json()] == [branch_three_id]

        response = client.post(
                "/auth/login",
                data={"username": "branch-staff", "password": "staff-password"},
            )
        assert response.status_code == 200, response.text
        staff_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = client.get("/company/employees", headers=staff_headers)
        assert response.status_code == 403, response.text
        response = client.get("/platform/companies", headers=company_headers)
        assert response.status_code == 403, response.text

        response = client.get("/warehouses", headers=staff_headers)
        assert response.status_code == 200, response.text
        assert {warehouse["id"] for warehouse in response.json()} == {warehouse_id, warehouse_three_id}

        response = client.get("/company/branches", headers=staff_headers)
        assert response.status_code == 200, response.text
        assert {branch["id"] for branch in response.json()} == {branch_two_id, branch_three_id}

        response = client.get("/company/employees", headers=company_headers)
        assert response.status_code == 200, response.text
        assert {employee["username"] for employee in response.json()} == {
            "company-admin",
            "branch-staff",
            "legacy-route-staff",
        }

        response = client.post(
                "/platform/companies",
                headers=platform_headers,
                json={
                    "name": "Company Two",
                    "code": "two",
                    "admin_username": "second-admin",
                    "admin_password": "second-password",
                },
            )
        assert response.status_code == 201, response.text
        company_two_id = response.json()["id"]

        response = client.post(
            "/auth/login",
            data={"username": "second-admin", "password": "second-password"},
        )
        assert response.status_code == 200, response.text
        second_company_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        response = client.post(
            "/customers",
            headers=second_company_headers,
            json={"name": "Shared name"},
        )
        assert response.status_code == 201, response.text
        second_customer_id = response.json()["id"]
        response = client.post(
            "/products",
            headers=second_company_headers,
            json={"sku": "SAME-SKU", "name": "Second company product"},
        )
        assert response.status_code == 201, response.text
        second_product_id = response.json()["id"]

        response = client.post(
            "/customers",
            headers=company_headers,
            json={"name": "Shared name"},
        )
        assert response.status_code == 201, response.text
        first_customer_id = response.json()["id"]
        response = client.post(
            "/products",
            headers=company_headers,
            json={"sku": "SAME-SKU", "name": "First company product"},
        )
        assert response.status_code == 201, response.text
        first_product_id = response.json()["id"]
        assert first_customer_id != second_customer_id
        assert first_product_id != second_product_id

        response = client.get("/reports/dashboard", headers=company_headers)
        assert response.status_code == 200, response.text
        assert response.json()["products"] == 1
        assert response.json()["customers"] == 1
        assert response.json()["warehouses"] == 2

        response = client.get("/reports/dashboard", headers=second_company_headers)
        assert response.status_code == 200, response.text
        assert response.json()["products"] == 1
        assert response.json()["customers"] == 1
        assert response.json()["warehouses"] == 0

        response = client.get("/customers", headers=company_headers)
        assert response.status_code == 200, response.text
        assert [customer["id"] for customer in response.json()] == [first_customer_id]
        response = client.get("/products", headers=company_headers)
        assert response.status_code == 200, response.text
        assert [product["id"] for product in response.json()] == [first_product_id]

        response = client.get("/company", headers=company_headers)
        assert response.status_code == 200, response.text
        assert response.json()["id"] == company_id
        response = client.get("/company", headers=second_company_headers)
        assert response.status_code == 200, response.text
        assert response.json()["id"] == company_two_id
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
