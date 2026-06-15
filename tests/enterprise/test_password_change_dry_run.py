from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


HEADERS = {"X-Actor": "sec", "X-Roles": "security_admin"}


def _secret() -> str:
    return f"runtime-secret-{uuid4().hex}"


def test_password_change_dry_run_uses_vendor_specific_masked_commands() -> None:
    client = TestClient(app)
    secret = _secret()
    response = client.post(
        "/api/v1/jobs/password-change",
        headers=HEADERS,
        json={
            "requested_by": "sec",
            "devices": [
                {"ip_address": "192.0.2.1", "vendor": "Cisco", "model": "Cat2960-48"},
                {"ip_address": "192.0.2.2", "vendor": "Huawei", "model": "S5735"},
                {"ip_address": "192.0.2.3", "vendor": "HPE", "model": "HPE 1910-24G"},
            ],
            "username": "admin",
            "new_password": secret,
        },
    )

    assert response.status_code == 202
    devices = response.json()["dry_run"]["devices"]
    assert [device["driver"] for device in devices] == ["CiscoIOSDriver", "HuaweiVRPDriver", "HPComwareDriver"]
    assert "username admin secret <redacted>" in devices[0]["config_commands"]
    assert "local-user admin password irreversible-cipher <redacted>" in devices[1]["config_commands"]
    assert "password irreversible-cipher <redacted>" in devices[2]["config_commands"]
    assert secret not in response.text
    assert all(device["apply_supported"] for device in devices)
    assert all(device["verification_required"] for device in devices)
