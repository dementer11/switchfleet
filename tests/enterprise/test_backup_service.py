from app.repositories.devices import DeviceRepository
from app.schemas.device import DeviceInput
from app.services.backup_service import BackupService


def _device_id(service: BackupService) -> str:
    device = DeviceRepository(service.session).create_or_update_from_input(
        DeviceInput(ip_address="192.0.2.10", vendor="Cisco", model="Cat2960-48")
    )
    return str(device.id)


def test_backup_service_encrypts_config_and_returns_masked_config() -> None:
    service = BackupService()
    device_id = _device_id(service)

    backup = service.create_backup(device_id, actor="alice", config_text="username admin secret VerySecret\n")

    stored = service.repository.get(backup.id)
    assert "VerySecret" not in stored.config_text
    fetched = service.read_backup(backup.id, include_config=True)
    assert fetched.config_text == "username admin secret <redacted>\n"


def test_backup_diff_is_masked() -> None:
    service = BackupService()
    device_id = _device_id(service)
    first = service.create_backup(device_id, actor="alice", config_text="vlan 100\nusername admin secret VerySecret\n")
    second = service.create_backup(device_id, actor="alice", config_text="vlan 200\nusername admin secret NewSecret\n")

    diff = service.diff(first.id, second.id)

    assert "-vlan 100" in diff
    assert "+vlan 200" in diff
    assert "VerySecret" not in diff
    assert "NewSecret" not in diff
