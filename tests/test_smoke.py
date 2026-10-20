import os
import sys
from pathlib import Path

# Ensure the repository root is importable when pytest is invoked as a console script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# CI provides a disposable SQLite URL before the app is imported.
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/forgestock-test.db")
os.environ.setdefault("SESSION_SECRET", "test-only-session-secret-not-for-production")
os.environ.setdefault("SEED_DEMO_DATA", "false")
os.environ.setdefault("ADMIN_USERNAME", "ci-admin")
os.environ.setdefault("ADMIN_PASSWORD", "ci-test-password-not-production")

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



def test_authenticated_inventory_workflow_and_audited_stock():
    with TestClient(app) as client:
        login = client.post("/login", data={
            "username": os.environ["ADMIN_USERNAME"],
            "password": os.environ["ADMIN_PASSWORD"],
        }, follow_redirects=False)
        assert login.status_code == 303

        supplier = client.post("/api/suppliers", json={
            "name": "CI Supplier", "contact": "555-0100", "email": "ci@example.test"
        })
        assert supplier.status_code == 200
        supplier_id = supplier.json()["id"]

        product = client.post("/api/products", json={
            "code": "CI-FG-001", "name": "CI Product", "unit": "units",
            "quantity": 5, "min_stock": 2
        })
        assert product.status_code == 200
        product_id = product.json()["id"]

        adjustment = client.post("/api/stock-adjustments", json={
            "item_type": "Finished Good", "item_id": product_id,
            "transaction_type": "Stock Out", "quantity": 2,
            "note": "CI stock adjustment"
        })
        assert adjustment.status_code == 200
        assert adjustment.json()["item"]["quantity"] == 3

        material = client.post("/api/materials", json={
            "code": "CI-RM-001", "name": "CI Material", "category": "Metals",
            "unit": "kg", "quantity": 10, "min_stock": 1,
            "supplier_id": supplier_id
        })
        assert material.status_code == 200
        assert material.json()["supplier"] == "CI Supplier"
