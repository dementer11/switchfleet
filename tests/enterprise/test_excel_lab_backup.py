from __future__ import annotations

from pathlib import Path

from app.core.config import Settings, get_settings
from app.services.excel_inventory import load_excel_inventory
from app.services.excel_lab_runtime import ExcelLabBackupRunner, StaticCommandTransport
from app.services.file_credential_vault import FileCredentialVault
from app.services.file_lab_state import FileLabState
from app.services.real_lab_apply_runner import LabSshTransportFactory
from tests.enterprise.excel_lab_helpers import write_inventory


class FakeFactory(LabSshTransportFactory):
    def __init__(self, transport: StaticCommandTransport):
        self.transport = transport

    def create(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return self.transport


def test_excel_lab_backup_uses_fake_transport_and_saves_sanitized_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    get_settings.cache_clear()
    device = load_excel_inventory(write_inventory(tmp_path / "inventory.xlsx"))[0]
    state = FileLabState(tmp_path / ".switchfleet_lab")
    vault = FileCredentialVault(state)
    vault.create_or_update(name="lab-admin", username="admin", secret="VaultSecret")
    fake = StaticCommandTransport(output="hostname sw1\nusername admin secret SHOULD_NOT_LEAK\n#")

    result = ExcelLabBackupRunner(
        state,
        vault,
        settings=Settings(environment="test", secret_key="excel-lab-secret-key", lab_device_allowlist=device.ip_address),
        transport_factory=FakeFactory(fake),
    ).backup_device(device, credential_ref="lab-admin")

    assert result.command_count == 1
    assert fake.commands == ["show running-config"]
    backup = state.latest_backup_for(device.id)
    assert backup is not None
    config_text = (state.paths.root / backup["config_path"]).read_text(encoding="utf-8")
    assert "SHOULD_NOT_LEAK" not in config_text
