from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_liveness():
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


def test_app_config_uses_api_envelope():
    response = client.get("/api/v1/app-config")
    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["app_name"] == "Karunya Sparsham"
    assert payload["data"]["financial_writes_require_online"] is True
    assert payload["meta"]["request_id"]


def test_protected_endpoint_requires_authentication():
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"
