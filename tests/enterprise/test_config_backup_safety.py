from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.session import SessionLocal
from app.main import app
from app.repositories.device_inventory import DeviceInventoryRepository
from app.services.config_backup_service import ConfigBackupService
from app.transports.dummy_transport import DummyTransport


def test_config_backup_safety_no_config_transport_methods_are_called(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail_send_config(self: DummyTransport, commands: list[str], timeout_seconds: int = 60) -> object:
        raise AssertionError("Config backup must not call send_config")

    monkeypatch.setattr(DummyTransport, "send_config", fail_send_config)
    session = SessionLocal()
    device, _created = DeviceInventoryRepository(session).upsert_device(
        {
            "management_ip": "10.66.0.1",
            "hostname": "safe-backup",
            "vendor": "Cisco",
            "model": "Cat2960-48",
            "driver_name": "CiscoIOSDriver",
        }
    )
    snapshot, _diff = ConfigBackupService(session).backup_device_config(str(device.id), actor="netadmin")

    assert snapshot.config_text
    assert "configure terminal" not in snapshot.config_text
    assert "write memory" not in snapshot.config_text


def test_config_backup_safety_no_restore_apply_endpoint_and_existing_guards_remain() -> None:
    client = TestClient(app)

    assert Settings(environment="test").allow_real_device_apply is False
    assert client.post("/api/v1/config-backups/restore-plans/not-a-plan/apply").status_code == 404
    assert client.post("/api/v1/jobs/not-a-job/run-next-batch").status_code in {403, 404}
