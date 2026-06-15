from __future__ import annotations

from app.db.session import SessionLocal
from app.repositories.devices import DeviceRepository
from app.schemas.device import DeviceInput
from app.services.backup_service import BackupService


def _device_id(service: BackupService) -> str:
    device = DeviceRepository(service.session).create_or_update_from_input(
        DeviceInput(ip_address="192.0.2.20", vendor="Huawei", model="S5735")
    )
    return str(device.id)


def test_backups_are_encrypted_in_database_and_diff_is_masked() -> None:
    service = BackupService(SessionLocal())
    device_id = _device_id(service)

    first = service.create_backup(device_id, actor="alice", config_text="vlan 100\nusername admin secret VerySecret\n")
    second = service.create_backup(device_id, actor="alice", config_text="vlan 200\nusername admin secret NewSecret\n")

    stored = service.repository.get(first.id)
    assert "VerySecret" not in stored.config_text
    assert first.config_hash == service.hash_config("vlan 100\nusername admin secret VerySecret\n")
    fetched = service.read_backup(first.id, include_config=True)
    assert fetched.config_text == "vlan 100\nusername admin secret <redacted>\n"

    diff = service.diff(first.id, second.id)
    assert "-vlan 100" in diff
    assert "+vlan 200" in diff
    assert "VerySecret" not in diff
    assert "NewSecret" not in diff
