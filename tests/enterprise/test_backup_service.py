from app.services.backup_service import BackupService
from app.services.runtime_state import get_runtime_state


def test_backup_service_encrypts_config_and_returns_masked_config() -> None:
    service = BackupService()

    backup = service.create_backup("device-1", actor="alice", config_text="username admin secret VerySecret\n")

    stored = get_runtime_state().backups[backup.id]
    assert "VerySecret" not in stored.encrypted_config_text
    fetched = service.read_backup(backup.id, include_config=True)
    assert fetched.config_text == "username admin secret <redacted>\n"


def test_backup_diff_is_masked() -> None:
    service = BackupService()
    first = service.create_backup("device-1", actor="alice", config_text="vlan 100\nusername admin secret VerySecret\n")
    second = service.create_backup("device-1", actor="alice", config_text="vlan 200\nusername admin secret NewSecret\n")

    diff = service.diff(first.id, second.id)

    assert "-vlan 100" in diff
    assert "+vlan 200" in diff
    assert "VerySecret" not in diff
    assert "NewSecret" not in diff

