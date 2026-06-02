from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.vendor_driver_contracts import VendorOperation
from app.db.session import SessionLocal
from app.main import app
from tests.enterprise.lab_apply_helpers import SECRET_KEY, allowed_lab_payload, create_lab_device

HEADERS = {"X-Actor": "netadmin", "X-Roles": "network_admin"}
VIEWER = {"X-Actor": "viewer", "X-Roles": "viewer"}


def _enable_lab_env(monkeypatch, device_id: str) -> None:
    monkeypatch.setenv("NCP_SECRET_KEY", SECRET_KEY)
    monkeypatch.setenv("NCP_ALLOW_REAL_DEVICE_APPLY", "true")
    monkeypatch.setenv("NCP_LAB_REAL_APPLY_ENABLED", "true")
    monkeypatch.setenv("NCP_PRODUCTION_REAL_APPLY_ENABLED", "false")
    monkeypatch.setenv("NCP_LAB_DEVICE_ALLOWLIST", device_id)
    get_settings.cache_clear()


def test_lab_apply_api_evaluate_and_execute_fake_success(monkeypatch) -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    payload = allowed_lab_payload(session, device)
    _enable_lab_env(monkeypatch, str(device.id))
    client = TestClient(app)

    evaluated = client.post("/api/v1/lab-apply/evaluate", headers=HEADERS, json=payload.model_dump(mode="json"))
    executed = client.post("/api/v1/lab-apply/execute", headers=HEADERS, json=payload.model_dump(mode="json"))

    assert evaluated.status_code == 200
    assert evaluated.json()["allowed"] is True
    assert executed.status_code == 200
    assert executed.json()["executed"] is True
    assert executed.json()["fake_transport"] is True
    assert "VerySecret" not in executed.text


def test_lab_apply_api_execute_denies_until_gates_pass(monkeypatch) -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    _enable_lab_env(monkeypatch, str(device.id))
    client = TestClient(app)

    denied = client.post(
        "/api/v1/lab-apply/execute",
        headers=HEADERS,
        json={"device_id": str(device.id), "operation": VendorOperation.password_change.value},
    )

    assert denied.status_code == 200
    assert denied.json()["executed"] is False
    assert denied.json()["decision"]["allowed"] is False


def test_lab_apply_api_rbac_and_no_generic_apply_or_run(monkeypatch) -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    _enable_lab_env(monkeypatch, str(device.id))
    client = TestClient(app)

    viewer = client.post(
        "/api/v1/lab-apply/execute",
        headers=VIEWER,
        json={"device_id": str(device.id), "operation": VendorOperation.password_change.value},
    )

    assert viewer.status_code == 403
    assert client.post("/api/v1/apply", headers=HEADERS).status_code == 404
    assert client.post("/api/v1/lab-apply/run", headers=HEADERS).status_code == 404


def test_lab_apply_api_requires_authenticated_actor(monkeypatch) -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    _enable_lab_env(monkeypatch, str(device.id))
    client = TestClient(app)

    response = client.post(
        "/api/v1/lab-apply/evaluate",
        json={"device_id": str(device.id), "operation": VendorOperation.password_change.value},
    )

    assert response.status_code == 403
