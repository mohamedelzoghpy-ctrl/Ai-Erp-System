from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


def _grant_section(client, headers, user_id: int, codes):
    """نظام الصلاحيات: قسم مؤقت للموظف + إسناده."""
    sec = client.post("/access-sections", headers=headers, json={"code": f"t{user_id}", "name": "قسم اختبار"}).json()
    client.put(f"/access-sections/{sec['id']}/permissions", headers=headers, json={"permission_codes": codes})
    client.put(f"/auth/users/{user_id}/section", headers=headers, json={"section_id": sec["id"]})


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
                json={"username": "platform", "password": "long-password-123", "full_name": "Platform"},
            )
        assert response.status_code == 201, response.text
        for path in (
            "/pos/invoices",
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
            data={"username": "platform", "password": "long-password-123"},
        )
        assert response.status_code == 200, response.text
        platform_token = response.json()["access_token"]
        platform_headers = {"Authorization": f"Bearer {platform_token}"}

        response = client.post(
                "/platform/companies",
                headers=platform_headers,
                json={
                    "name": "Company One",
                    "max_warehouses_per_branch": 1,
                    "max_branches": 3,
                    "admin_username": "company-admin",
                    "admin_full_name": "Company Admin Name",
                    "admin_password": "company-password-123",
                },
            )
        assert response.status_code == 201, response.text
        company_id = response.json()["id"]
        admin_info = client.get(f"/platform/companies/{company_id}/admin", headers=platform_headers)
        assert admin_info.status_code == 200, admin_info.text
        assert admin_info.json()["full_name"] == "Company Admin Name"

        response = client.post(
                "/auth/login",
                data={"username": "company-admin", "password": "company-password-123"},
            )
        assert response.status_code == 200, response.text
        company_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = client.post(
                "/company/branches",
                headers=company_headers,
                json={"name": "Branch Two"},
            )
        assert response.status_code == 201, response.text
        branch_two_id = response.json()["id"]

        response = client.post(
                "/warehouses",
                headers=company_headers,
                json={"name": "Warehouse One", "branch_id": branch_two_id},
            )
        assert response.status_code == 201, response.text
        warehouse_id = response.json()["id"]
        assert response.json()["code"] == "WH-warehouse-one"
        platform_departments = client.get(f"/platform/companies/{company_id}/departments", headers=platform_headers)
        assert platform_departments.status_code == 200, platform_departments.text
        assert platform_departments.json() == []
        platform_department = client.post(
            f"/platform/companies/{company_id}/departments",
            headers=platform_headers,
            json={"name": "Accounting", "description": "Finance team"},
        )
        assert platform_department.status_code == 201, platform_department.text
        department_id = platform_department.json()["id"]
        assert platform_department.json()["code"] == "DEPT-accounting"
        switched = client.post("/auth/switch-company", headers=platform_headers, json={"company_id": company_id})
        assert switched.status_code == 200, switched.text
        response = client.get("/company/departments", headers=company_headers)
        assert response.status_code == 200, response.text
        assert [department["id"] for department in response.json()] == [department_id]
        department = response.json()[0]
        updated_department = client.patch(
            f"/company/departments/{department_id}",
            headers=company_headers,
            json={"name": "Accounting and Finance", "description": "Finance and accounting team", "is_active": True},
        )
        assert updated_department.status_code == 200, updated_department.text
        assert updated_department.json()["name"] == "Accounting and Finance"
        duplicate_department = client.post("/company/departments", headers=company_headers, json={"name": "Accounting and Finance"})
        assert duplicate_department.status_code == 409, duplicate_department.text
        all_branch_employee = client.post(
            "/company/employees",
            headers=company_headers,
            json={"username": "all-branch-login", "full_name": "All Branch User", "password": "staff-password-123", "role": "staff", "department_id": department_id, "all_branches": True},
        )
        assert all_branch_employee.status_code == 201, all_branch_employee.text
        employee_code = all_branch_employee.json()["employee_code"]
        assert employee_code.isdigit()
        assert all_branch_employee.json()["username"] == "all-branch-login"
        assert all_branch_employee.json()["full_name"] == "All Branch User"
        employee_login = client.post("/auth/login", data={"username": "all-branch-login", "password": "staff-password-123"})
        assert employee_login.status_code == 200, employee_login.text
        assert all_branch_employee.json()["department_id"] == department_id
        assert all_branch_employee.json()["department_name"] == "Accounting and Finance"
        assert all_branch_employee.json()["all_branches"] is True
        assert set(all_branch_employee.json()["branch_ids"]) == {branch_two_id, company_id}
        single_branch_employee = client.post(
            "/company/employees",
            headers=company_headers,
            json={"username": "single-branch-login", "password": "staff-password-123", "role": "staff", "department_id": department_id, "branch_ids": [branch_two_id]},
        )
        assert single_branch_employee.status_code == 201, single_branch_employee.text
        assert single_branch_employee.json()["employee_code"].isdigit()
        assert single_branch_employee.json()["employee_code"] != employee_code
        assert single_branch_employee.json()["all_branches"] is False
        assert single_branch_employee.json()["branch_ids"] == [branch_two_id]
        switched = client.post("/auth/switch-company", headers=platform_headers, json={"company_id": company_id})
        assert switched.status_code == 200, switched.text
        update_warehouse = client.patch(
            f"/platform/companies/{company_id}/warehouses/{warehouse_id}",
            headers=platform_headers,
            json={"location": "Edited location"},
        )
        assert update_warehouse.status_code == 200, update_warehouse.text
        assert update_warehouse.json()["location"] == "Edited location"
        linked_product = client.post(
            "/products",
            headers=company_headers,
            json={"name": "Warehouse linked product", "warehouse_id": warehouse_id},
        )
        assert linked_product.status_code == 201, linked_product.text
        delete_warehouse = client.delete(
            f"/platform/companies/{company_id}/warehouses/{warehouse_id}",
            headers=platform_headers,
        )
        assert delete_warehouse.status_code == 409, delete_warehouse.text
        switched = client.post("/auth/switch-company", headers=platform_headers, json={"company_id": 1})
        assert switched.status_code == 200, switched.text

        response = client.post(
                "/warehouses",
                headers=company_headers,
                json={"name": "Warehouse Two", "branch_id": branch_two_id},
            )
        assert response.status_code == 409, response.text
        response = client.post(
            "/company/branches",
            headers=company_headers,
            json={"name": "Branch Three"},
        )
        assert response.status_code == 201, response.text
        branch_three_id = response.json()["id"]
        response = client.post(
            "/warehouses",
            headers=company_headers,
            json={"name": "Warehouse Three", "branch_id": branch_three_id},
        )
        assert response.status_code == 201, response.text
        warehouse_three_id = response.json()["id"]
        assert response.json()["code"] == "WH-warehouse-three"

        switched = client.post("/auth/switch-company", headers=platform_headers, json={"company_id": company_id})
        assert switched.status_code == 200, switched.text
        delete_branch = client.delete(
            f"/platform/companies/{company_id}/branches/{branch_two_id}",
            headers=platform_headers,
        )
        assert delete_branch.status_code == 409, delete_branch.text
        delete_branch = client.delete(
            f"/platform/companies/{company_id}/branches/{branch_three_id}",
            headers=platform_headers,
        )
        assert delete_branch.status_code == 409, delete_branch.text
        branch_to_delete = client.post(
            "/company/branches",
            headers=company_headers,
            json={"name": "Branch to delete"},
        )
        assert branch_to_delete.status_code == 409, branch_to_delete.text
        limit_update = client.patch(
            f"/platform/companies/{company_id}",
            headers=platform_headers,
            json={"max_branches": 4},
        )
        assert limit_update.status_code == 200, limit_update.text
        assert limit_update.json()["max_branches"] == 4
        branch_to_delete = client.post(
            "/company/branches",
            headers=company_headers,
            json={"name": "Branch to delete"},
        )
        assert branch_to_delete.status_code == 201, branch_to_delete.text
        deletable_branch_id = branch_to_delete.json()["id"]
        delete_branch = client.delete(
            f"/platform/companies/{company_id}/branches/{deletable_branch_id}",
            headers=platform_headers,
        )
        assert delete_branch.status_code == 204, delete_branch.text
        switched = client.post("/auth/switch-company", headers=platform_headers, json={"company_id": 1})
        assert switched.status_code == 200, switched.text

        response = client.post(
                "/company/employees",
                headers=company_headers,
                json={
                    "username": "branch-staff-legacy",
                    "password": "staff-password-123",
                    "role": "staff",
                    "branch_ids": [branch_three_id],
                    "warehouse_ids": [warehouse_id],
                },
            )
        assert response.status_code == 201, response.text
        branch_staff_username = response.json()["username"]
        assert branch_staff_username == "branch-staff-legacy"
        assert response.json()["employee_code"].isdigit()
        assert response.json()["branch_ids"] == [branch_three_id]
        assert response.json()["warehouse_ids"] == [warehouse_id]
        _grant_section(
            client,
            company_headers,
            [u for u in client.get("/auth/users", headers=company_headers).json() if u["username"] == "branch-staff-legacy"][0]["id"],
            ["admin.branch.view", "inventory.warehouse.view"],
        )

        response = client.post(
            "/auth/users",
            headers=company_headers,
            json={
                "username": "unscoped-staff",
                "password": "staff-password-123",
                "role": "staff",
            },
        )
        assert response.status_code == 422, response.text

        response = client.post(
            "/auth/users",
            headers=company_headers,
            json={
                "username": "legacy-route-staff",
                "password": "staff-password-123",
                "role": "staff",
                "branch_ids": [branch_three_id],
            },
        )
        assert response.status_code == 201, response.text
        _grant_section(client, company_headers, response.json()["id"], ["admin.branch.view", "inventory.warehouse.view"])

        response = client.post(
            "/auth/login",
            data={"username": "legacy-route-staff", "password": "staff-password-123"},
        )
        assert response.status_code == 200, response.text
        legacy_staff_headers = {"Authorization": "Bearer " + response.json()["access_token"]}
        response = client.get("/company/branches", headers=legacy_staff_headers)
        assert response.status_code == 200, response.text
        assert [branch["id"] for branch in response.json()] == [branch_three_id]

        response = client.post(
                "/auth/login",
                data={"username": branch_staff_username, "password": "staff-password-123"},
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
            "platform",
            branch_staff_username,
            "legacy-route-staff",
            all_branch_employee.json()["username"],
            single_branch_employee.json()["username"],
        }

        response = client.post(
                "/platform/companies",
                headers=platform_headers,
                json={
                    "name": "Company Two",
                    "code": "two",
                    "admin_username": "second-admin",
                    "admin_password": "second-password-123",
                },
            )
        assert response.status_code == 201, response.text
        company_two_id = response.json()["id"]

        response = client.post(
            "/auth/login",
            data={"username": "second-admin", "password": "second-password-123"},
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
        assert response.json()["products"] == 2
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
        assert {product["id"] for product in response.json()} == {first_product_id, linked_product.json()["id"]}

        response = client.get("/company", headers=company_headers)
        assert response.status_code == 200, response.text
        assert response.json()["id"] == company_id
        assert response.json()["max_branches"] == 4
        response = client.get("/company", headers=second_company_headers)
        assert response.status_code == 200, response.text
        assert response.json()["id"] == company_two_id

        # Platform bank management
        created_bank = client.post(
            f"/platform/companies/{company_id}/banks",
            headers=platform_headers,
            json={"name": "Misr Bank", "account_number": "123456", "opening_balance": 5000},
        )
        assert created_bank.status_code == 201, created_bank.text
        bank_id = created_bank.json()["id"]
        assert created_bank.json()["name"] == "Misr Bank"
        assert created_bank.json()["balance"] == "5000.00"

        banks_list = client.get(f"/platform/companies/{company_id}/banks", headers=platform_headers)
        assert banks_list.status_code == 200, banks_list.text
        assert any(b["id"] == bank_id for b in banks_list.json())

        updated_bank = client.patch(
            f"/platform/companies/{company_id}/banks/{bank_id}",
            headers=platform_headers,
            json={"name": "Banque Misr Updated"},
        )
        assert updated_bank.status_code == 200, updated_bank.text
        assert updated_bank.json()["name"] == "Banque Misr Updated"

        del_bank = client.delete(f"/platform/companies/{company_id}/banks/{bank_id}", headers=platform_headers)
        assert del_bank.status_code == 204, del_bank.text
        deleted_department = client.delete(f"/platform/companies/{company_id}/departments/{department_id}", headers=platform_headers)
        assert deleted_department.status_code == 204, deleted_department.text
        assert client.get(f"/platform/companies/{company_id}/departments", headers=platform_headers).json() == []
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_company_license_expiry_blocks_usage_and_renewal_restores(monkeypatch):
    """رخصة الاستخدام: انتهاؤها يوقف عمليات العمل (غير مدير المنصة) والتجديد بكلمة سر المورّد يعيد التشغيل."""
    monkeypatch.setenv("LICENSE_RENEWAL_PASSWORD", "vendor-secret-123")
    from datetime import date, timedelta

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
        assert client.post("/auth/setup", json={"username": "platform", "password": "long-password-123"}).status_code == 201
        platform_token = client.post("/auth/login", data={"username": "platform", "password": "long-password-123"}).json()["access_token"]
        platform_headers = {"Authorization": f"Bearer {platform_token}"}

        resp = client.post(
            "/platform/companies",
            headers=platform_headers,
            json={
                "name": "Licensed Co",
                "admin_username": "co-admin",
                "admin_full_name": "Co Admin",
                "admin_password": "company-password-123",
            },
        )
        assert resp.status_code == 201, resp.text
        company_id = resp.json()["id"]

        co_token = client.post("/auth/login", data={"username": "co-admin", "password": "company-password-123"}).json()["access_token"]
        co_headers = {"Authorization": f"Bearer {co_token}"}

        # بلا رخصة (NULL = غير مقيّد): العمل طبيعي
        assert client.post("/company/branches", headers=co_headers, json={"name": "B1"}).status_code == 201

        # رخصة منتهية (أمس): مسارات الذات تعمل وعمليات العمل محجوبة
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        resp = client.put(f"/platform/companies/{company_id}/license", headers=platform_headers, json={"license_until": yesterday, "license_password": "vendor-secret-123"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["license_until"] == yesterday

        assert client.get("/auth/me", headers=co_headers).status_code == 200  # self يمر
        blocked = client.get("/company/branches", headers=co_headers)
        assert blocked.status_code == 403, blocked.text
        assert "انتهت رخصة" in blocked.text
        # مدير الشركة (admin) لا يتجاوز الرخصة — الحجب تعاقدي
        # ومدير المنصة يتجاوز ويستطيع العمل على الشركة المنتهية
        assert client.get("/platform/companies", headers=platform_headers).status_code == 200

        # التجديد لتاريخ مستقبلي يعيد التشغيل
        renewed = (date.today() + timedelta(days=30)).isoformat()
        resp = client.put(f"/platform/companies/{company_id}/license", headers=platform_headers, json={"license_until": renewed, "license_password": "vendor-secret-123"})
        assert resp.status_code == 200, resp.text
        assert client.get("/company/branches", headers=co_headers).status_code == 200

        # إلغاء القيد (NULL) يعيد الوضع غير المقيّد
        resp = client.put(f"/platform/companies/{company_id}/license", headers=platform_headers, json={"license_until": None, "license_password": "vendor-secret-123"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["license_until"] is None
        assert client.get("/company/branches", headers=co_headers).status_code == 200

        # الرخصة ممنوعة على غير مدير المنصة
        assert client.put(
            f"/platform/companies/{company_id}/license", headers=co_headers, json={"license_until": yesterday, "license_password": "vendor-secret-123"}
        ).status_code == 403
        # كلمة سر خاطئة → مرفوض
        resp = client.put(
            f"/platform/companies/{company_id}/license",
            headers=platform_headers,
            json={"license_until": renewed, "license_password": "wrong-password"},
        )
        assert resp.status_code == 403, resp.text
        assert "كلمة سر التجديد غير صحيحة" in resp.text

        # بدون ضبط متغير البيئة على الخادم → التجديد متعذر (503)
        monkeypatch.delenv("LICENSE_RENEWAL_PASSWORD", raising=False)
        resp = client.put(
            f"/platform/companies/{company_id}/license",
            headers=platform_headers,
            json={"license_until": renewed, "license_password": "vendor-secret-123"},
        )
        assert resp.status_code == 503, resp.text

    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
