from fastapi.testclient import TestClient
from app.main import app


def test_material_lookup_data_is_initialized():
    with TestClient(app) as client:
        login = client.post("/login", data={
            "username": "ci-admin",
            "password": "ci-test-password-not-production",
        }, follow_redirects=False)
        assert login.status_code == 303
        response = client.get("/api/materials")
        assert response.status_code == 200
        assert {"Metals", "Polymers", "Packaging", "Electrical"}.issubset(set(response.json()["categories"]))
        assert "suppliers" in response.json()
