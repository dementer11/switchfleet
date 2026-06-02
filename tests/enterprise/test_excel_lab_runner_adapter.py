from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from app.core.vendor_driver_contracts import VendorOperation
from app.services.excel_inventory import load_excel_inventory
from app.services.excel_lab_runtime import ExcelLabApplyExecutor
from app.services.excel_lab_safety import ExcelLabSafetyRequest, ExcelLabSafetyService
from app.services.file_credential_vault import FileCredentialVault
from app.services.file_lab_state import FileLabState
from app.services.vendor_command_templates import VendorCommandTemplateService, command_hash
from tests.enterprise.excel_lab_helpers import write_inventory


def test_excel_lab_apply_fake_executes_only_after_allowed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    monkeypatch.setenv("NCP_LAB_DEVICE_ALLOWLIST", "10.13.4.67")
    get_settings.cache_clear()
    device = load_excel_inventory(write_inventory(tmp_path / "inventory.xlsx"))[0]
    state = FileLabState(tmp_path / ".switchfleet_lab")
    vault = FileCredentialVault(state)
    vault.create_or_update(name="lab-admin", username="admin", secret="VaultSecret")
    commands = VendorCommandTemplateService().render(__import__("app.core.transport_strategy", fromlist=["DeviceFamily"]).DeviceFamily.cisco_ios, VendorOperation.vlan_create, {"vlan_id": 123, "name": "TEST"})
    hash_value = command_hash(commands)
    state.save_dry_run({"device_id": device.id, "operation": "vlan_create", "command_hash": hash_value})
    state.save_backup(device.id, "hostname sw1", {"config_hash": "safe"})
    state.save_lab_validation({"device_id": device.id, "capability": "vlan_create"})
    decision, runtime = ExcelLabSafetyService(state, vault).evaluate(
        ExcelLabSafetyRequest(
            device=device,
            operation=VendorOperation.vlan_create,
            credential_ref="lab-admin",
            command_parameters={"vlan_id": 123, "name": "TEST"},
            simulation_hash=hash_value,
        )
    )

    result = ExcelLabApplyExecutor(state, vault).execute(
        device=device,
        safety_decision=decision,
        transport_decision=runtime,
        credential_ref="lab-admin",
        real_lab=False,
    )

    assert result.executed is True
    assert result.fake_transport is True
    assert state.has_active_lock(device.id) is False


def test_excel_lab_apply_denied_does_not_decrypt_or_execute(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    get_settings.cache_clear()
    device = load_excel_inventory(write_inventory(tmp_path / "inventory.xlsx"))[0]
    state = FileLabState(tmp_path / ".switchfleet_lab")
    vault = FileCredentialVault(state)
    vault.create_or_update(name="lab-admin", username="admin", secret="VaultSecret")
    decision, runtime = ExcelLabSafetyService(state, vault).evaluate(
        ExcelLabSafetyRequest(
            device=device,
            operation=VendorOperation.vlan_create,
            credential_ref="lab-admin",
            command_parameters={"vlan_id": 123, "name": "TEST"},
            simulation_hash="missing",
        )
    )

    result = ExcelLabApplyExecutor(state, vault).execute(
        device=device,
        safety_decision=decision,
        transport_decision=runtime,
        credential_ref="lab-admin",
        real_lab=True,
    )

    assert result.executed is False
    assert result.command_count == 0
