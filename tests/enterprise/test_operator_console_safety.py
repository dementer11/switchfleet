from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.transports.dummy_transport import DummyTransport
from tests.enterprise.operator_console_helpers import seed_operator_console
from app.db.session import SessionLocal


def test_operator_console_safety_posture_and_no_destructive_routes() -> None:
    client = TestClient(app)
    headers = {"X-Actor": "viewer", "X-Roles": "viewer"}
    safety = client.get("/api/v1/operator-console/safety", headers=headers).json()

    assert Settings(environment="test").allow_real_device_apply is False
    assert safety["real_apply_enabled"] is False
    assert safety["apply_endpoints_present"] is False
    assert safety["destructive_run_endpoints_present"] is False
    assert client.post("/api/v1/operator-console/apply", headers=headers).status_code == 404
    assert client.post("/api/v1/operator-console/run", headers=headers).status_code == 404


def test_operator_console_does_not_open_transport_or_execute_workflows(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail_open(self: DummyTransport) -> None:
        raise AssertionError("Operator console must not open transports")

    def fail_send_config(self: DummyTransport, commands: list[str], timeout_seconds: int = 60) -> object:
        raise AssertionError("Operator console must not call send_config")

    monkeypatch.setattr(DummyTransport, "open", fail_open)
    monkeypatch.setattr(DummyTransport, "send_config", fail_send_config)
    session = SessionLocal()
    seed_operator_console(session)
    client = TestClient(app)

    response = client.get("/api/v1/operator-console/dashboard", headers={"X-Actor": "viewer", "X-Roles": "viewer"})

    assert response.status_code == 200
    rendered = str(response.json()).casefold()
    assert "should_not_leak" not in rendered
    assert "username admin secret" not in rendered
