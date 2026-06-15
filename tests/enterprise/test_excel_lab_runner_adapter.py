from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from app.core.vendor_driver_contracts import VendorOperation
from app.services.excel_inventory import load_excel_inventory
from app.services.excel_lab_runtime import ExcelLabApplyExecutor
from app.services.excel_lab_safety import ExcelLabSafetyRequest, ExcelLabSafetyService
from app.services.file_credential_vault import FileCredentialVault
from app.services.file_lab_state import FileLabState
from app.services.vendor_command_templates import VendorCommandTemplateService, command_hash, private_command_hash
from tests.enterprise.excel_lab_helpers import write_inventory


def test_excel_lab_apply_fake_executes_only_after_allowed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    monkeypatch.setenv("NCP_LAB_DEVICE_ALLOWLIST", "192.0.2.67")
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


def test_excel_lab_fake_password_execute_writes_only_redacted_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    monkeypatch.setenv("NCP_LAB_DEVICE_ALLOWLIST", "192.0.2.67")
    get_settings.cache_clear()
    device = load_excel_inventory(write_inventory(tmp_path / "inventory.xlsx"))[0]
    state = FileLabState(tmp_path / ".switchfleet_lab")
    vault = FileCredentialVault(state)
    vault.create_or_update(name="lab-admin", username="admin", secret="VaultSecret")
    commands = VendorCommandTemplateService().render(
        __import__("app.core.transport_strategy", fromlist=["DeviceFamily"]).DeviceFamily.cisco_ios,
        VendorOperation.password_change,
        {"username": "admin", "password": "NewPasswordSecret", "level": 15},
    )
    hash_value = command_hash(commands)
    state.save_dry_run(
        {
            "device_id": device.id,
            "operation": "password_change",
            "command_hash": hash_value,
            "private_command_hash": private_command_hash(commands, secret_key="excel-lab-secret-key"),
        }
    )
    state.save_backup(device.id, "hostname sw1", {"config_hash": "safe"})
    state.save_lab_validation({"device_id": device.id, "capability": "password_change"})
    decision, runtime = ExcelLabSafetyService(state, vault).evaluate(
        ExcelLabSafetyRequest(
            device=device,
            operation=VendorOperation.password_change,
            credential_ref="lab-admin",
            command_parameters={"username": "admin", "password": "NewPasswordSecret", "level": 15},
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
    state_text = "\n".join(path.read_text(encoding="utf-8") for path in state.paths.root.rglob("*") if path.is_file())

    assert result.executed is True
    assert result.fake_transport is True
    assert "NewPasswordSecret" not in state_text
    assert "VaultSecret" not in state_text
    assert "<redacted>" in state_text


def test_excel_lab_real_execute_requires_real_apply_evaluation_before_decrypt(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    monkeypatch.setenv("NCP_LAB_DEVICE_ALLOWLIST", "192.0.2.67")
    get_settings.cache_clear()
    device = load_excel_inventory(write_inventory(tmp_path / "inventory.xlsx"))[0]
    state = FileLabState(tmp_path / ".switchfleet_lab")
    vault = FileCredentialVault(state)
    vault.create_or_update(name="lab-admin", username="admin", secret="VaultSecret")
    commands = VendorCommandTemplateService().render(
        __import__("app.core.transport_strategy", fromlist=["DeviceFamily"]).DeviceFamily.cisco_ios,
        VendorOperation.vlan_create,
        {"vlan_id": 123, "name": "TEST"},
    )
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
            require_real_apply=False,
        )
    )

    def fail_decrypt(_ref: str) -> str:
        raise AssertionError("real execute must not decrypt when real apply gates were not evaluated")

    monkeypatch.setattr(vault, "decrypt_for_execution_after_safety", fail_decrypt)
    result = ExcelLabApplyExecutor(state, vault).execute(
        device=device,
        safety_decision=decision,
        transport_decision=runtime,
        credential_ref="lab-admin",
        real_lab=True,
    )

    assert decision.allowed is True
    assert decision.real_apply_requested is False
    assert result.executed is False
    assert result.command_count == 0
    assert "real apply gates" in str(result.error)
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

    def fail_decrypt(_ref: str) -> str:
        raise AssertionError("denied execute must not decrypt credentials")

    monkeypatch.setattr(vault, "decrypt_for_execution_after_safety", fail_decrypt)
    result = ExcelLabApplyExecutor(state, vault).execute(
        device=device,
        safety_decision=decision,
        transport_decision=runtime,
        credential_ref="lab-admin",
        real_lab=True,
    )

    assert result.executed is False
    assert result.command_count == 0


def test_excel_lab_apply_active_lock_between_evaluate_and_execute_blocks_before_decrypt(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    monkeypatch.setenv("NCP_LAB_DEVICE_ALLOWLIST", "192.0.2.67")
    monkeypatch.setenv("NCP_ALLOW_REAL_DEVICE_APPLY", "true")
    monkeypatch.setenv("NCP_LAB_REAL_APPLY_ENABLED", "true")
    monkeypatch.setenv("NCP_PRODUCTION_REAL_APPLY_ENABLED", "false")
    get_settings.cache_clear()
    device = load_excel_inventory(write_inventory(tmp_path / "inventory.xlsx"))[0]
    state = FileLabState(tmp_path / ".switchfleet_lab")
    vault = FileCredentialVault(state)
    vault.create_or_update(name="lab-admin", username="admin", secret="VaultSecret")
    commands = VendorCommandTemplateService().render(
        __import__("app.core.transport_strategy", fromlist=["DeviceFamily"]).DeviceFamily.cisco_ios,
        VendorOperation.vlan_create,
        {"vlan_id": 123, "name": "TEST"},
    )
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
            require_real_apply=True,
        )
    )
    state.reserve_lock(device.id, "concurrent operator")

    def fail_decrypt(_ref: str) -> str:
        raise AssertionError("active lock must block before credential decrypt")

    monkeypatch.setattr(vault, "decrypt_for_execution_after_safety", fail_decrypt)
    result = ExcelLabApplyExecutor(state, vault).execute(
        device=device,
        safety_decision=decision,
        transport_decision=runtime,
        credential_ref="lab-admin",
        real_lab=True,
    )

    assert decision.allowed is True
    assert decision.real_apply_requested is True
    assert result.executed is False
    assert result.command_count == 0
    assert "already has an active lab lock" in str(result.error)
