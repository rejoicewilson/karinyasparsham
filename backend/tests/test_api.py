from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from app.main import app
from app.schemas.api import AdminCollectionBatchCreate, MemberCreate


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


def test_handover_endpoints_require_authentication():
    assert client.get("/api/v1/agent/handovers").status_code == 401
    assert client.get("/api/v1/admin/handovers").status_code == 401
    assert client.post("/api/v1/admin/collection-batches", json={}).status_code == 401


def test_member_ard_number_is_optional_and_digits_only():
    common = {
        "login_id": "member-1",
        "temporary_password": "temporary-password",
        "member_code": "KSD-02-M001",
        "full_name": "Member One",
        "phone": "9000000000",
        "taluk_id": "00000000-0000-4000-8000-000000000001",
        "joined_on": "2026-01-01",
    }
    assert MemberCreate(**common).ard_no is None
    assert MemberCreate(**common, ard_no="2469002").ard_no == "2469002"
    with pytest.raises(ValidationError):
        MemberCreate(**common, ard_no="ARD-2469002")


def test_admin_collection_batch_requires_timezone_and_entries():
    common = {
        "client_request_id": "00000000-0000-4000-8000-000000000010",
        "agent_profile_id": "00000000-0000-4000-8000-000000000011",
        "declared_amount": "100.00",
        "received_at": "2026-09-20T10:30:00+05:30",
        "entries": [{
            "member_id": "00000000-0000-4000-8000-000000000012",
            "collection_type": "DEATH_CONTRIBUTION",
            "case_obligation_id": "00000000-0000-4000-8000-000000000013",
            "amount": "100.00",
            "method": "CASH",
        }],
    }
    assert AdminCollectionBatchCreate(**common).declared_amount == 100
    with pytest.raises(ValidationError):
        AdminCollectionBatchCreate(**{**common, "received_at": "2026-09-20T10:30:00"})
    with pytest.raises(ValidationError):
        AdminCollectionBatchCreate(**{**common, "entries": []})
