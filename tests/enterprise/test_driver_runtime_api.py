from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.transport_strategy import TransportKind
from app.db.models.device import Device
from app.db.session import SessionLocal
from app.main import app

HEADERS = {"X-Actor": "viewer", "X-Roles": "viewer"}


def test_driver_runtime_api_endpoints_exist_and_are_get_only() -> None:
    client = TestClient(app)
    paths = [
        "/api/v1/driver-runtime/profiles",
        "/api/v1/driver-runtime/profiles/cisco_ios",
        "/api/v1/driver-runtime/decision?vendor=Cisco&model=Catalyst%202960",
        "/api/v1/driver-runtime/summary",
        "/api/v1/driver-runtime/safety",
    ]

    for path in paths:
        assert client.get(path, headers=HEADERS).status_code == 200
        assert client.post(path, headers=HEADERS).status_code == 405
        assert client.put(path, headers=HEADERS).status_code == 405
        assert client.patch(path, headers=HEADERS).status_code == 405
        assert client.delete(path, headers=HEADERS).status_code == 405


def test_driver_runtime_decision_summary_and_safety_endpoints() -> None:
    client = TestClient(app)

    cisco = client.get("/api/v1/driver-runtime/decision?vendor=Cisco&model=Catalyst%202960", headers=HEADERS)
    bulat = client.get("/api/v1/driver-runtime/decision?vendor=Bulat&model=BS2500", headers=HEADERS)
    generic = client.get("/api/v1/driver-runtime/decision?vendor=Unknown&model=Unknown&driver_name=GenericSSHDriver", headers=HEADERS)
    summary = client.get("/api/v1/driver-runtime/summary", headers=HEADERS)
    safety = client.get("/api/v1/driver-runtime/safety", headers=HEADERS)

    assert cisco.status_code == 200
    assert cisco.json()["selected_transport"] == TransportKind.netmiko.value
    assert cisco.json()["config_apply_allowed"] is False
    assert bulat.json()["selected_transport"] == TransportKind.custom_cli.value
    assert bulat.json()["config_apply_allowed"] is False
    assert generic.json()["selected_transport"] == TransportKind.paramiko.value
    assert generic.json()["config_apply_allowed"] is False
    assert summary.json()["real_apply_certified_count"] == 0
    assert summary.json()["config_apply_allowed_globally"] is False
    assert safety.json()["apply_endpoint_added"] is False
    assert safety.json()["destructive_run_endpoint_added"] is False


def test_driver_runtime_device_decision_uses_inventory_device() -> None:
    session = SessionLocal()
    device = Device(
        ip_address="10.91.0.10",
        management_ip="10.91.0.10",
        hostname="edge-cisco",
        vendor="Cisco",
        model="Catalyst 2960",
        platform="ios",
        driver_name="CiscoIOSDriver",
    )
    session.add(device)
    session.commit()
    client = TestClient(app)

    response = client.get(f"/api/v1/driver-runtime/devices/{device.id}/decision", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["device_id"] == str(device.id)
    assert response.json()["hostname"] == "edge-cisco"
    assert response.json()["selected_transport"] == "netmiko"
    assert response.json()["config_apply_allowed"] is False


def test_driver_runtime_api_has_no_apply_or_run_endpoint() -> None:
    client = TestClient(app)
    routes = {route for route in app.openapi()["paths"] if "/api/v1/driver-runtime" in route}

    assert all("/apply" not in route for route in routes)
    assert all(not route.endswith("/run") for route in routes)
    assert client.post("/api/v1/driver-runtime/apply", headers=HEADERS).status_code == 404
    assert client.post("/api/v1/driver-runtime/run", headers=HEADERS).status_code == 404
