from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


HEADERS = {"X-Actor": "sec", "X-Roles": "security_admin"}
SECRET = "UltraSecret123!"


def test_password_change_dry_run_uses_vendor_specific_masked_commands() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/jobs/password-change",
        headers=HEADERS,
        json={
            "requested_by": "sec",
            "devices": [
                {"ip_address": "10.70.0.1", "vendor": "Cisco", "model": "Cat2960-48"},
                {"ip_address": "10.70.0.2", "vendor": "Huawei", "model": "S5735"},
                {"ip_address": "10.70.0.3", "vendor": "HPE", "model": "HPE 1910-24G"},
            ],
            "username": "admin",
            "new_password": SECRET,
        },
    )

    assert response.status_code == 202
    devices = response.json()["dry_run"]["devices"]
    assert [device["driver"] for device in devices] == ["CiscoIOSDriver", "HuaweiVRPDriver", "HPComwareDriver"]
    assert "username admin secret <redacted>" in devices[0]["config_commands"]
    assert "local-user admin password irreversible-cipher <redacted>" in devices[1]["config_commands"]
    assert "password irreversible-cipher <redacted>" in devices[2]["config_commands"]
    assert SECRET not in response.text
    assert all(device["apply_supported"] for device in devices)
    assert all(device["verification_required"] for device in devices)

