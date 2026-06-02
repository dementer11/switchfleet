from __future__ import annotations

from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.vendor_driver_contracts import VendorOperation
from app.services.excel_inventory import load_excel_inventory
from app.services.excel_lab_safety import ExcelLabSafetyRequest, ExcelLabSafetyService
from app.services.file_credential_vault import FileCredentialVault
from app.services.file_lab_state import FileLabState
from app.services.vendor_command_templates import VendorCommandTemplateService, command_hash
from tests.enterprise.excel_lab_helpers import write_inventory


def _state_with_secret(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    get_settings.cache_clear()
    state = FileLabState(tmp_path / ".switchfleet_lab")
    vault = FileCredentialVault(state)
    vault.create_or_update(name="lab-admin", username="admin", secret="VaultSecret")
    return state, vault


def test_excel_lab_safety_denies_missing_backup_allowlist_and_hash(tmp_path: Path, monkeypatch) -> None:
    device = load_excel_inventory(write_inventory(tmp_path / "inventory.xlsx"))[0]
    state, vault = _state_with_secret(tmp_path, monkeypatch)
    service = ExcelLabSafetyService(state, vault, settings=Settings(environment="test", secret_key="excel-lab-secret-key"))

    decision, _runtime = service.evaluate(
        ExcelLabSafetyRequest(
            device=device,
            operation=VendorOperation.vlan_create,
            credential_ref="lab-admin",
            command_parameters={"vlan_id": 123, "name": "TEST"},
            simulation_hash="missing",
        )
    )

    assert decision.allowed is False
    assert {"device_allowlist", "fresh_backup", "lab_validation", "simulation_hash"} <= set(decision.denied_gates)


def test_excel_lab_safety_allows_file_mode_after_required_records(tmp_path: Path, monkeypatch) -> None:
    device = load_excel_inventory(write_inventory(tmp_path / "inventory.xlsx"))[0]
    state, vault = _state_with_secret(tmp_path, monkeypatch)
    commands = VendorCommandTemplateService().render(device_family := __import__("app.core.transport_strategy", fromlist=["DeviceFamily"]).DeviceFamily.cisco_ios, VendorOperation.vlan_create, {"vlan_id": 123, "name": "TEST"})
    hash_value = command_hash(commands)
    state.save_dry_run({"device_id": device.id, "operation": "vlan_create", "command_hash": hash_value})
    state.save_backup(device.id, "hostname sw1\nusername admin secret <redacted>", {"config_hash": "safe"})
    state.save_lab_validation({"device_id": device.id, "capability": "vlan_create"})

    service = ExcelLabSafetyService(
        state,
        vault,
        settings=Settings(
            environment="test",
            secret_key="excel-lab-secret-key",
            lab_device_allowlist=device.ip_address,
        ),
    )
    decision, runtime = service.evaluate(
        ExcelLabSafetyRequest(
            device=device,
            operation=VendorOperation.vlan_create,
            credential_ref="lab-admin",
            command_parameters={"vlan_id": 123, "name": "TEST"},
            simulation_hash=hash_value,
        )
    )

    assert device_family.value == "cisco_ios"
    assert runtime.family.value == "cisco_ios"
    assert decision.allowed is True
    assert decision.production_allowed is False


def test_excel_lab_safety_blocks_unknown_and_eltex_config_apply(tmp_path: Path, monkeypatch) -> None:
    unknown, eltex = load_excel_inventory(
        write_inventory(
            tmp_path / "inventory.xlsx",
            [
                ["Active", "unknown", "Unknown SNMP Product", "10.13.4.71", "Huawei", "Switch", "Lab", "NetOps"],
                ["Active", "eltex", "MES2448", "10.13.4.72", "Eltex", "Switch", "Lab", "NetOps"],
            ],
        )
    )
    state, vault = _state_with_secret(tmp_path, monkeypatch)
    service = ExcelLabSafetyService(
        state,
        vault,
        settings=Settings(environment="test", secret_key="excel-lab-secret-key", lab_device_allowlist="10.13.4.71,10.13.4.72"),
    )

    for device in (unknown, eltex):
        decision, _runtime = service.evaluate(
            ExcelLabSafetyRequest(
                device=device,
                operation=VendorOperation.vlan_create,
                credential_ref="lab-admin",
                command_parameters={"vlan_id": 123, "name": "TEST"},
                simulation_hash="missing",
            )
        )
        assert decision.allowed is False
        assert "runtime_decision" in decision.denied_gates or "vendor_contract" in decision.denied_gates
