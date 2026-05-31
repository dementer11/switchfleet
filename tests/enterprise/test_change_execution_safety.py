from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.session import SessionLocal
from app.main import app
from app.repositories.change_executions import ChangeExecutionRepository
from app.services.change_execution_plan_service import ChangeExecutionPlanService
from app.transports.dummy_transport import DummyTransport
from tests.enterprise.change_execution_helpers import create_ready_vlan_source


def test_change_execution_has_no_apply_or_destructive_run_and_real_apply_default_off() -> None:
    client = TestClient(app)

    assert Settings(environment="test").allow_real_device_apply is False
    assert client.post("/api/v1/change-executions/not-found/apply").status_code == 404
    assert client.post("/api/v1/change-executions/not-found/run").status_code == 404


def test_change_execution_planning_and_simulation_never_open_transport(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail_open(self: DummyTransport) -> None:
        raise AssertionError("Change execution simulation must not open transports")

    def fail_send_config(self: DummyTransport, commands: list[str], timeout_seconds: int = 60) -> object:
        raise AssertionError("Change execution simulation must not call send_config")

    monkeypatch.setattr(DummyTransport, "open", fail_open)
    monkeypatch.setattr(DummyTransport, "send_config", fail_send_config)
    session = SessionLocal()
    source_id, _device_id = create_ready_vlan_source(session)
    execution = ChangeExecutionRepository(session).create_execution("safe", "vlan_change", "vlan_workflow", source_id=source_id)
    session.commit()

    steps = ChangeExecutionPlanService(SessionLocal()).build_execution_plan(str(execution.id))
    rendered = "\n".join(str(step.planned_action) for step in steps)

    assert steps
    assert "copy running-config startup-config" not in rendered.casefold()
    assert "write memory" not in rendered.casefold()


def test_change_execution_reports_do_not_expose_raw_configs_or_secrets() -> None:
    session = SessionLocal()
    source_id, _device_id = create_ready_vlan_source(session)
    execution = ChangeExecutionRepository(session).create_execution("safe report", "vlan_change", "vlan_workflow", source_id=source_id)
    session.commit()
    client = TestClient(app)
    headers = {"X-Actor": "viewer", "X-Roles": "viewer"}

    report = client.get(f"/api/v1/change-executions/{execution.id}/report", headers=headers)

    assert report.status_code == 200
    body = str(report.json()).casefold()
    assert "private-key" not in body
    assert "snmp-server community" not in body
    assert "password 0" not in body
