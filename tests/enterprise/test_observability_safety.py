from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.session import SessionLocal
from app.main import app
from app.transports.dummy_transport import DummyTransport
from tests.enterprise.operator_console_helpers import seed_operator_console

VIEWER_HEADERS = {"X-Actor": "viewer", "X-Roles": "viewer"}


def test_observability_has_no_apply_or_destructive_run_and_real_apply_default_off() -> None:
    client = TestClient(app)
    routes = {route for route in app.openapi()["paths"] if "/api/v1/observability" in route}

    assert Settings(environment="test").allow_real_device_apply is False
    assert all("/apply" not in route for route in routes)
    assert all(not route.endswith("/run") for route in routes)
    assert client.post("/api/v1/observability/apply", headers=VIEWER_HEADERS).status_code == 404
    assert client.post("/api/v1/observability/run", headers=VIEWER_HEADERS).status_code == 404


def test_observability_does_not_open_transport_or_execute_actions(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail_open(self: DummyTransport) -> None:
        raise AssertionError("Observability must not open transports")

    def fail_send_config(self: DummyTransport, commands: list[str], timeout_seconds: int = 60) -> object:
        raise AssertionError("Observability must not call send_config")

    monkeypatch.setattr(DummyTransport, "open", fail_open)
    monkeypatch.setattr(DummyTransport, "send_config", fail_send_config)
    session = SessionLocal()
    seed_operator_console(session)
    client = TestClient(app)

    for path in (
        "/api/v1/observability/operational-report",
        "/api/v1/observability/compliance-snapshot",
        "/api/v1/observability/safety-posture",
        "/api/v1/observability/workflow-activity",
        "/api/v1/observability/device-readiness",
        "/api/v1/observability/metrics-summary",
    ):
        response = client.get(path, headers=VIEWER_HEADERS)
        assert response.status_code == 200
        assert "SHOULD_NOT_LEAK" not in str(response.json())
