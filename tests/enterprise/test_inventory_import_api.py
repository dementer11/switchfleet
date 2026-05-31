from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


HEADERS = {"X-Actor": "netadmin", "X-Roles": "network_admin"}


def _payload(dry_run: bool) -> dict[str, object]:
    return {
        "source_type": "api",
        "filename": "inventory.json",
        "dry_run": dry_run,
        "strict": False,
        "items": [
            {
                "ip": "10.4.0.1",
                "hostname": "sw-core-1",
                "vendor": "Huawei",
                "model": "S5735",
                "site": "HQ",
                "tags": ["core"],
            }
        ],
    }


def test_inventory_import_dry_run_does_not_create_devices_and_reports() -> None:
    client = TestClient(app)
    response = client.post("/api/v1/inventory/import", headers=HEADERS, json=_payload(dry_run=True))
    devices = client.get("/api/v1/inventory/devices", headers=HEADERS)
    report = client.get(
        f"/api/v1/inventory/imports/{response.json()['batch']['id']}/driver-resolution-report",
        headers=HEADERS,
    )

    assert response.status_code == 201
    assert response.json()["dry_run"] is True
    assert devices.json() == []
    assert report.json()["devices"][0]["driver_name"] == "HuaweiVRPDriver"


def test_inventory_import_creates_devices_and_patch_metadata_is_restricted() -> None:
    client = TestClient(app)
    response = client.post("/api/v1/inventory/import", headers=HEADERS, json=_payload(dry_run=False))
    devices = client.get("/api/v1/inventory/devices?site=HQ", headers=HEADERS).json()
    device_id = devices[0]["id"]
    patched = client.patch(
        f"/api/v1/inventory/devices/{device_id}",
        headers=HEADERS,
        json={"site": "DC1", "location": "MDF", "rack": "R1", "role": "access", "tags": ["edge"]},
    )
    forbidden_field = client.patch(
        f"/api/v1/inventory/devices/{device_id}",
        headers=HEADERS,
        json={"vendor": "Changed"},
    )

    assert response.json()["batch"]["created_devices"] == 1
    assert patched.status_code == 200
    assert patched.json()["site"] == "DC1"
    assert patched.json()["tags"] == ["edge"]
    assert forbidden_field.status_code == 422


def test_inventory_import_rejects_duplicate_hostname_with_different_ip() -> None:
    client = TestClient(app)
    first = client.post(
        "/api/v1/inventory/import",
        headers=HEADERS,
        json={
            "source_type": "api",
            "dry_run": False,
            "items": [
                {
                    "ip": "10.4.1.1",
                    "hostname": "sw-conflict",
                    "vendor": "Cisco",
                    "model": "Cat2960-48",
                }
            ],
        },
    )
    second = client.post(
        "/api/v1/inventory/import",
        headers=HEADERS,
        json={
            "source_type": "api",
            "dry_run": False,
            "items": [
                {
                    "ip": "10.4.1.2",
                    "hostname": "sw-conflict",
                    "vendor": "Cisco",
                    "model": "Cat2960-48",
                }
            ],
        },
    )
    devices = client.get("/api/v1/inventory/devices", headers=HEADERS).json()
    conflicts = [device for device in devices if device["hostname"] == "sw-conflict"]

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["batch"]["invalid_rows"] == 1
    assert second.json()["validation_report"]["items"][0]["row_status"] == "invalid"
    assert "different management_ip" in second.json()["validation_report"]["items"][0]["error_message"]
    assert len(conflicts) == 1
