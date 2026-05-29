from fastapi.testclient import TestClient

from app.main import app


def test_vlan_change_endpoint_returns_dry_run() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/jobs/vlan-change",
        json={
            "requested_by": "alice",
            "devices": [{"ip_address": "10.0.0.1", "vendor": "Cisco", "model": "Cat2960-48"}],
            "intent": {"vlan_id": 100, "name": "USERS", "state": "present"},
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["job_id"]
    assert payload["status"] == "pending_approval"
    assert payload["approval_required"] is True
    assert payload["apply_allowed"] is False
    assert payload["dry_run"]["devices"][0]["driver"] == "CiscoIOSDriver"
    assert "configure terminal" in payload["dry_run"]["devices"][0]["commands"]
