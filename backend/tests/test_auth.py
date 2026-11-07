from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


def test_first_admin_setup_and_login():
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
        setup = client.post(
            "/auth/setup",
            json={"username": "auth-test-admin", "password": "strong-password-123"},
        )
        assert setup.status_code == 201, setup.text

        login = client.post(
            "/auth/login",
            data={"username": "auth-test-admin", "password": "strong-password-123"},
        )
        assert login.status_code == 200, login.text
        assert login.json()["access_token"]

        rejected = client.post(
            "/auth/login",
            data={"username": "auth-test-admin", "password": "wrong-password"},
        )
        assert rejected.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
