from __future__ import annotations

from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.exceptions import SafetyError
from app.core.vendor_driver_contracts import VendorOperation
from app.services.excel_inventory import load_excel_inventory
from app.services.excel_lab_runtime import ExcelLabBackupRunner, StaticCommandTransport
from app.services.excel_lab_safety import ExcelLabSafetyRequest, ExcelLabSafetyService
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

    assert result.device_ip == device.ip_address
    assert result.hostname == device.hostname
    assert result.label == device.label
    assert result.vendor == device.vendor
    assert result.model == device.model
    assert result.command_count == 1
    assert fake.commands == ["show running-config"]
    backup = state.latest_backup_for(device.id)
    assert backup is not None
    assert backup["device_ip"] == device.ip_address
    assert backup["internal_device_id"] == device.id
    assert Path(backup["config_path"]).parts[:2] == ("backups", device.ip_address)
    config_text = (state.paths.root / backup["config_path"]).read_text(encoding="utf-8")
    assert "SHOULD_NOT_LEAK" not in config_text


def test_excel_lab_comware_backup_disables_paging_before_collection(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    get_settings.cache_clear()
    device = load_excel_inventory(
        write_inventory(
            tmp_path / "inventory.xlsx",
            [["Active", "sw-comware", "S4210", "192.0.2.90", "3Com", "Switch", "Lab", "NetOps"]],
        )
    )[0]
    state = FileLabState(tmp_path / ".switchfleet_lab")
    vault = FileCredentialVault(state)
    vault.create_or_update(name="lab-admin", username="admin", secret="VaultSecret")
    fake = StaticCommandTransport(output="display current-configuration\nconfig\n<169-4-408-0.176>")

    result = ExcelLabBackupRunner(
        state,
        vault,
        settings=Settings(environment="test", secret_key="excel-lab-secret-key", lab_device_allowlist=device.ip_address),
        transport_factory=FakeFactory(fake),
    ).backup_device(device, credential_ref="lab-admin")

    assert result.command_count == 1
    assert fake.commands == ["screen-length disable", "screen-length 0 temporary", "display current-configuration"]


def test_excel_lab_backup_rejects_incomplete_paged_output(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    get_settings.cache_clear()
    device = load_excel_inventory(write_inventory(tmp_path / "inventory.xlsx"))[0]
    state = FileLabState(tmp_path / ".switchfleet_lab")
    vault = FileCredentialVault(state)
    vault.create_or_update(name="lab-admin", username="admin", secret="VaultSecret")
    fake = StaticCommandTransport(output="partial config\n---- More ----")

    try:
        ExcelLabBackupRunner(
            state,
            vault,
            settings=Settings(environment="test", secret_key="excel-lab-secret-key", lab_device_allowlist=device.ip_address),
            transport_factory=FakeFactory(fake),
        ).backup_device(device, credential_ref="lab-admin")
    except SafetyError as exc:
        assert "paging marker" in str(exc)
    else:
        raise AssertionError("Paged backup output was not rejected")

    assert state.latest_backup_for(device.id) is None
    decision, _runtime = ExcelLabSafetyService(
        state,
        vault,
        settings=Settings(environment="test", secret_key="excel-lab-secret-key", lab_device_allowlist=device.ip_address),
    ).evaluate(
        ExcelLabSafetyRequest(
            device=device,
            operation=VendorOperation.vlan_create,
            credential_ref="lab-admin",
            command_parameters={"vlan_id": 123, "name": "TEST"},
            simulation_hash="missing",
        )
    )
    assert "fresh_backup" in decision.denied_gates


def test_excel_lab_qtech_backup_path_remains_successful(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    get_settings.cache_clear()
    device = load_excel_inventory(
        write_inventory(
            tmp_path / "inventory.xlsx",
            [["Active", "qtech-lab", "QSW-4610", "192.0.2.91", "QTECH", "Switch", "Lab", "NetOps"]],
        )
    )[0]
    state = FileLabState(tmp_path / ".switchfleet_lab")
    vault = FileCredentialVault(state)
    vault.create_or_update(name="lab-admin", username="admin", secret="VaultSecret")
    fake = StaticCommandTransport(output="hostname qtech\nQSW-4610>")

    result = ExcelLabBackupRunner(
        state,
        vault,
        settings=Settings(environment="test", secret_key="excel-lab-secret-key", lab_device_allowlist=device.ip_address),
        transport_factory=FakeFactory(fake),
    ).backup_device(device, credential_ref="lab-admin")

    assert result.command_count == 1
    assert fake.commands == ["terminal length 0", "show running-config"]
    backup = state.latest_backup_for(device.id)
    assert backup is not None
    config_text = (state.paths.root / backup["config_path"]).read_text(encoding="utf-8")
    assert "QSW-4610>" not in config_text
    assert "hostname qtech" in config_text
