import os

# CI provides a disposable SQLite URL before the app is imported.
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/forgestock-test.db")
os.environ.setdefault("SESSION_SECRET", "test-only-session-secret-not-for-production")
os.environ.setdefault("SEED_DEMO_DATA", "false")

from fastapi.testclient import TestClient
from app.main import app, hash_password, verify_password


def test_health_reports_live_database_connection():
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["database_connected"] is True


def test_login_page_renders_without_demo_credentials():
    with TestClient(app) as client:
        response = client.get("/login")
        assert response.status_code == 200
        assert "Welcome back" in response.text
        assert "admin123" not in response.text


def test_inventory_api_requires_authentication():
    with TestClient(app) as client:
        response = client.get("/api/materials")
        assert response.status_code == 401


def test_password_hash_verification():
    hashed = hash_password("a-long-test-password")
    assert hashed.startswith("pbkdf2_sha256$")
    assert verify_password("a-long-test-password", hashed)
    assert not verify_password("wrong-password", hashed)
