from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.vendor_driver_contracts import VendorOperation
from app.services.driver_capability_matrix import DriverCapabilityMatrix
from app.services.excel_inventory import load_excel_inventory
from app.services.excel_lab_safety import ExcelLabSafetyRequest, ExcelLabSafetyService
from app.services.file_credential_vault import FileCredentialVault
from app.services.file_lab_state import FileLabState
from app.services.vendor_command_templates import VendorCommandTemplateService, command_hash, private_command_hash
from tests.enterprise.excel_lab_helpers import write_inventory


def _state_with_secret(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    get_settings.cache_clear()
    state = FileLabState(tmp_path / ".switchfleet_lab")
    vault = FileCredentialVault(state)
    vault.create_or_update(name="lab-admin", username="admin", secret="VaultSecret")
    return state, vault


def _save_matching_validation(
    state: FileLabState,
    device,
    capability: str,
    **overrides,
):
    decision = DriverCapabilityMatrix().decide(
        vendor=device.vendor,
        model=device.model,
        platform=device.platform,
        driver_name=device.driver_name,
        device_id=device.id,
        hostname=device.hostname,
    )
    record = {
        "device_id": device.id,
        "capability": capability,
        "vendor": device.vendor,
        "model": device.model,
        "driver_name": device.driver_name,
        "platform": device.platform,
        "family": decision.family.value,
        "selected_transport": decision.selected_transport.value,
    }
    record.update(overrides)
    return state.save_lab_validation(record)


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


def test_excel_lab_safety_does_not_allowlist_internal_generated_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    get_settings.cache_clear()
    device = load_excel_inventory(write_inventory(tmp_path / "inventory.xlsx"))[0]
    state, vault = _state_with_secret(tmp_path, monkeypatch)

    decision, _runtime = ExcelLabSafetyService(
        state,
        vault,
        settings=Settings(environment="test", secret_key="excel-lab-secret-key", lab_device_allowlist=device.id),
    ).evaluate(
        ExcelLabSafetyRequest(
            device=device,
            operation=VendorOperation.vlan_create,
            credential_ref="lab-admin",
            command_parameters={"vlan_id": 123, "name": "TEST"},
            simulation_hash="missing",
        )
    )

    assert "device_allowlist" in decision.denied_gates
    assert any(device.ip_address in reason for reason in decision.reasons)


def test_excel_lab_safety_allows_file_mode_after_required_records(tmp_path: Path, monkeypatch) -> None:
    device = load_excel_inventory(write_inventory(tmp_path / "inventory.xlsx"))[0]
    state, vault = _state_with_secret(tmp_path, monkeypatch)
    commands = VendorCommandTemplateService().render(device_family := __import__("app.core.transport_strategy", fromlist=["DeviceFamily"]).DeviceFamily.cisco_ios, VendorOperation.vlan_create, {"vlan_id": 123, "name": "TEST"})
    hash_value = command_hash(commands)
    state.save_dry_run({"device_id": device.id, "operation": "vlan_create", "command_hash": hash_value})
    state.save_backup(device.id, "hostname sw1\nusername admin secret <redacted>", {"config_hash": "safe"})
    _save_matching_validation(state, device, "vlan_create")

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


def test_excel_lab_safety_requires_exact_lab_validation_capability(tmp_path: Path, monkeypatch) -> None:
    device = load_excel_inventory(write_inventory(tmp_path / "inventory.xlsx"))[0]
    state, vault = _state_with_secret(tmp_path, monkeypatch)
    commands = VendorCommandTemplateService().render(
        __import__("app.core.transport_strategy", fromlist=["DeviceFamily"]).DeviceFamily.cisco_ios,
        VendorOperation.vlan_create,
        {"vlan_id": 123, "name": "TEST"},
    )
    hash_value = command_hash(commands)
    state.save_dry_run({"device_id": device.id, "operation": "vlan_create", "command_hash": hash_value})
    state.save_backup(device.id, "hostname sw1\nusername admin secret <redacted>", {"config_hash": "safe"})
    state.save_lab_validation({"device_id": device.id, "capability": "config_apply"})

    service = ExcelLabSafetyService(
        state,
        vault,
        settings=Settings(
            environment="test",
            secret_key="excel-lab-secret-key",
            lab_device_allowlist=device.ip_address,
        ),
    )
    decision, _runtime = service.evaluate(
        ExcelLabSafetyRequest(
            device=device,
            operation=VendorOperation.vlan_create,
            credential_ref="lab-admin",
            command_parameters={"vlan_id": 123, "name": "TEST"},
            simulation_hash=hash_value,
        )
    )

    assert decision.allowed is False
    assert "lab_validation" in decision.denied_gates
    assert state.latest_validation_for(device.id, "vlan_create") is None


def test_excel_lab_safety_requires_runtime_matching_lab_validation(tmp_path: Path, monkeypatch) -> None:
    device = load_excel_inventory(write_inventory(tmp_path / "inventory.xlsx"))[0]
    state, vault = _state_with_secret(tmp_path, monkeypatch)
    commands = VendorCommandTemplateService().render(
        __import__("app.core.transport_strategy", fromlist=["DeviceFamily"]).DeviceFamily.cisco_ios,
        VendorOperation.vlan_create,
        {"vlan_id": 123, "name": "TEST"},
    )
    hash_value = command_hash(commands)
    state.save_dry_run({"device_id": device.id, "operation": "vlan_create", "command_hash": hash_value})
    state.save_backup(device.id, "hostname sw1\nusername admin secret <redacted>", {"config_hash": "safe"})
    _save_matching_validation(state, device, "vlan_create", family="huawei_vrp", selected_transport="paramiko")

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

    assert runtime.family.value == "cisco_ios"
    assert decision.allowed is False
    assert "lab_validation" in decision.denied_gates
    assert any("runtime-matching lab certification" in reason for reason in decision.reasons)


def test_excel_lab_real_apply_evaluation_does_not_decrypt_credentials(tmp_path: Path, monkeypatch) -> None:
    device = load_excel_inventory(write_inventory(tmp_path / "inventory.xlsx"))[0]
    state, vault = _state_with_secret(tmp_path, monkeypatch)
    commands = VendorCommandTemplateService().render(
        __import__("app.core.transport_strategy", fromlist=["DeviceFamily"]).DeviceFamily.cisco_ios,
        VendorOperation.vlan_create,
        {"vlan_id": 123, "name": "TEST"},
    )
    hash_value = command_hash(commands)
    state.save_dry_run({"device_id": device.id, "operation": "vlan_create", "command_hash": hash_value})
    state.save_backup(device.id, "hostname sw1\nusername admin secret <redacted>", {"config_hash": "safe"})
    _save_matching_validation(state, device, "vlan_create")

    def fail_decrypt(_ref: str) -> str:
        raise AssertionError("evaluate-apply must not decrypt credentials")

    monkeypatch.setattr(vault, "decrypt_for_execution_after_safety", fail_decrypt)
    service = ExcelLabSafetyService(
        state,
        vault,
        settings=Settings(
            environment="test",
            secret_key="excel-lab-secret-key",
            lab_device_allowlist=device.ip_address,
            allow_real_device_apply=True,
            lab_real_apply_enabled=True,
            production_real_apply_enabled=False,
        ),
    )

    decision, runtime = service.evaluate(
        ExcelLabSafetyRequest(
            device=device,
            operation=VendorOperation.vlan_create,
            credential_ref="lab-admin",
            command_parameters={"vlan_id": 123, "name": "TEST"},
            simulation_hash=hash_value,
            require_real_apply=True,
        )
    )

    assert runtime.family.value == "cisco_ios"
    assert decision.allowed is True
    assert decision.real_apply_requested is True
    assert decision.production_allowed is False


def test_excel_lab_evaluate_apply_does_not_require_secret_key_for_metadata_only_check(tmp_path: Path, monkeypatch) -> None:
    device = load_excel_inventory(write_inventory(tmp_path / "inventory.xlsx"))[0]
    state, _vault = _state_with_secret(tmp_path, monkeypatch)
    commands = VendorCommandTemplateService().render(
        __import__("app.core.transport_strategy", fromlist=["DeviceFamily"]).DeviceFamily.cisco_ios,
        VendorOperation.vlan_create,
        {"vlan_id": 123, "name": "TEST"},
    )
    hash_value = command_hash(commands)
    state.save_dry_run({"device_id": device.id, "operation": "vlan_create", "command_hash": hash_value})
    state.save_backup(device.id, "hostname sw1\nusername admin secret <redacted>", {"config_hash": "safe"})
    _save_matching_validation(state, device, "vlan_create")
    monkeypatch.delenv("NCP_SECRET_KEY", raising=False)
    get_settings.cache_clear()
    vault = FileCredentialVault(state)
    service = ExcelLabSafetyService(
        state,
        vault,
        settings=Settings(
            environment="test",
            secret_key=None,
            lab_device_allowlist=device.ip_address,
        ),
    )

    decision, _runtime = service.evaluate(
        ExcelLabSafetyRequest(
            device=device,
            operation=VendorOperation.vlan_create,
            credential_ref="lab-admin",
            command_parameters={"vlan_id": 123, "name": "TEST"},
            simulation_hash=hash_value,
        )
    )

    assert decision.allowed is True
    assert "credential_reference" in decision.satisfied_gates


def test_excel_lab_real_apply_evaluation_requires_secret_key_before_decrypt_transport(tmp_path: Path, monkeypatch) -> None:
    device = load_excel_inventory(write_inventory(tmp_path / "inventory.xlsx"))[0]
    state, _vault = _state_with_secret(tmp_path, monkeypatch)
    commands = VendorCommandTemplateService().render(
        __import__("app.core.transport_strategy", fromlist=["DeviceFamily"]).DeviceFamily.cisco_ios,
        VendorOperation.vlan_create,
        {"vlan_id": 123, "name": "TEST"},
    )
    hash_value = command_hash(commands)
    state.save_dry_run({"device_id": device.id, "operation": "vlan_create", "command_hash": hash_value})
    state.save_backup(device.id, "hostname sw1\nusername admin secret <redacted>", {"config_hash": "safe"})
    _save_matching_validation(state, device, "vlan_create")
    monkeypatch.delenv("NCP_SECRET_KEY", raising=False)
    get_settings.cache_clear()
    vault = FileCredentialVault(state)

    def fail_decrypt(_ref: str) -> str:
        raise AssertionError("real apply evaluation must not decrypt credentials")

    monkeypatch.setattr(vault, "decrypt_for_execution_after_safety", fail_decrypt)
    service = ExcelLabSafetyService(
        state,
        vault,
        settings=Settings(
            environment="test",
            secret_key=None,
            lab_device_allowlist=device.ip_address,
            allow_real_device_apply=True,
            lab_real_apply_enabled=True,
            production_real_apply_enabled=False,
        ),
    )

    decision, _runtime = service.evaluate(
        ExcelLabSafetyRequest(
            device=device,
            operation=VendorOperation.vlan_create,
            credential_ref="lab-admin",
            command_parameters={"vlan_id": 123, "name": "TEST"},
            simulation_hash=hash_value,
            require_real_apply=True,
        )
    )

    assert decision.allowed is False
    assert "environment_flags" in decision.denied_gates
    assert any("NCP_SECRET_KEY" in reason for reason in decision.reasons)


def test_excel_lab_safety_denies_stale_backup(tmp_path: Path, monkeypatch) -> None:
    device = load_excel_inventory(write_inventory(tmp_path / "inventory.xlsx"))[0]
    state, vault = _state_with_secret(tmp_path, monkeypatch)
    commands = VendorCommandTemplateService().render(
        __import__("app.core.transport_strategy", fromlist=["DeviceFamily"]).DeviceFamily.cisco_ios,
        VendorOperation.vlan_create,
        {"vlan_id": 123, "name": "TEST"},
    )
    hash_value = command_hash(commands)
    state.save_dry_run({"device_id": device.id, "operation": "vlan_create", "command_hash": hash_value})
    state.save_backup(device.id, "hostname sw1\nusername admin secret <redacted>", {"config_hash": "safe"})
    _save_matching_validation(state, device, "vlan_create")
    index_path = state.paths.backups / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["backups"][0]["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    index_path.write_text(json.dumps(index), encoding="utf-8")

    service = ExcelLabSafetyService(
        state,
        vault,
        settings=Settings(
            environment="test",
            secret_key="excel-lab-secret-key",
            lab_device_allowlist=device.ip_address,
            lab_backup_max_age_hours=24,
        ),
    )
    decision, _runtime = service.evaluate(
        ExcelLabSafetyRequest(
            device=device,
            operation=VendorOperation.vlan_create,
            credential_ref="lab-admin",
            command_parameters={"vlan_id": 123, "name": "TEST"},
            simulation_hash=hash_value,
        )
    )

    assert decision.allowed is False
    assert "fresh_backup" in decision.denied_gates
    assert any("newer than 24 hours" in reason for reason in decision.reasons)


def test_excel_lab_safety_requires_dry_run_for_same_device_and_operation(tmp_path: Path, monkeypatch) -> None:
    target, other = load_excel_inventory(
        write_inventory(
            tmp_path / "inventory.xlsx",
            [
                ["Active", "target", "Catalyst 2960", "192.0.2.67", "Cisco", "Switch", "Lab", "NetOps"],
                ["Active", "other", "Catalyst 2960", "192.0.2.68", "Cisco", "Switch", "Lab", "NetOps"],
            ],
        )
    )
    state, vault = _state_with_secret(tmp_path, monkeypatch)
    commands = VendorCommandTemplateService().render(
        __import__("app.core.transport_strategy", fromlist=["DeviceFamily"]).DeviceFamily.cisco_ios,
        VendorOperation.vlan_create,
        {"vlan_id": 123, "name": "TEST"},
    )
    hash_value = command_hash(commands)
    state.save_dry_run({"device_id": other.id, "operation": "vlan_create", "command_hash": hash_value})
    state.save_backup(target.id, "hostname sw1\nusername admin secret <redacted>", {"config_hash": "safe"})
    _save_matching_validation(state, target, "vlan_create")
    service = ExcelLabSafetyService(
        state,
        vault,
        settings=Settings(
            environment="test",
            secret_key="excel-lab-secret-key",
            lab_device_allowlist=target.ip_address,
        ),
    )

    decision, _runtime = service.evaluate(
        ExcelLabSafetyRequest(
            device=target,
            operation=VendorOperation.vlan_create,
            credential_ref="lab-admin",
            command_parameters={"vlan_id": 123, "name": "TEST"},
            simulation_hash=hash_value,
        )
    )

    assert decision.allowed is False
    assert "simulation_hash" in decision.denied_gates
    assert any("for this device and operation" in reason for reason in decision.reasons)


def test_excel_lab_safety_denies_active_lock(tmp_path: Path, monkeypatch) -> None:
    device = load_excel_inventory(write_inventory(tmp_path / "inventory.xlsx"))[0]
    state, vault = _state_with_secret(tmp_path, monkeypatch)
    commands = VendorCommandTemplateService().render(
        __import__("app.core.transport_strategy", fromlist=["DeviceFamily"]).DeviceFamily.cisco_ios,
        VendorOperation.vlan_create,
        {"vlan_id": 123, "name": "TEST"},
    )
    hash_value = command_hash(commands)
    state.save_dry_run({"device_id": device.id, "operation": "vlan_create", "command_hash": hash_value})
    state.save_backup(device.id, "hostname sw1\nusername admin secret <redacted>", {"config_hash": "safe"})
    _save_matching_validation(state, device, "vlan_create")
    state.reserve_lock(device.id, "already running")
    service = ExcelLabSafetyService(
        state,
        vault,
        settings=Settings(
            environment="test",
            secret_key="excel-lab-secret-key",
            lab_device_allowlist=device.ip_address,
        ),
    )

    decision, _runtime = service.evaluate(
        ExcelLabSafetyRequest(
            device=device,
            operation=VendorOperation.vlan_create,
            credential_ref="lab-admin",
            command_parameters={"vlan_id": 123, "name": "TEST"},
            simulation_hash=hash_value,
        )
    )

    assert decision.allowed is False
    assert "lock_conflict" in decision.denied_gates
    assert any("active Excel lab lock" in reason for reason in decision.reasons)


def test_excel_lab_safety_ignores_non_approved_validation_records(tmp_path: Path, monkeypatch) -> None:
    device = load_excel_inventory(write_inventory(tmp_path / "inventory.xlsx"))[0]
    state, vault = _state_with_secret(tmp_path, monkeypatch)
    commands = VendorCommandTemplateService().render(
        __import__("app.core.transport_strategy", fromlist=["DeviceFamily"]).DeviceFamily.cisco_ios,
        VendorOperation.vlan_create,
        {"vlan_id": 123, "name": "TEST"},
    )
    hash_value = command_hash(commands)
    state.save_dry_run({"device_id": device.id, "operation": "vlan_create", "command_hash": hash_value})
    state.save_backup(device.id, "hostname sw1\nusername admin secret <redacted>", {"config_hash": "safe"})
    validation = _save_matching_validation(state, device, "vlan_create")
    validation["status"] = "rejected"
    state.paths.lab_validations.write_text(json.dumps({"lab_validations": [validation]}), encoding="utf-8")
    service = ExcelLabSafetyService(
        state,
        vault,
        settings=Settings(
            environment="test",
            secret_key="excel-lab-secret-key",
            lab_device_allowlist=device.ip_address,
        ),
    )

    decision, _runtime = service.evaluate(
        ExcelLabSafetyRequest(
            device=device,
            operation=VendorOperation.vlan_create,
            credential_ref="lab-admin",
            command_parameters={"vlan_id": 123, "name": "TEST"},
            simulation_hash=hash_value,
        )
    )

    assert decision.allowed is False
    assert "lab_validation" in decision.denied_gates


def test_excel_lab_safety_binds_secret_operations_to_private_dry_run_hash(tmp_path: Path, monkeypatch) -> None:
    device = load_excel_inventory(write_inventory(tmp_path / "inventory.xlsx"))[0]
    state, vault = _state_with_secret(tmp_path, monkeypatch)
    dry_run_commands = VendorCommandTemplateService().render(
        __import__("app.core.transport_strategy", fromlist=["DeviceFamily"]).DeviceFamily.cisco_ios,
        VendorOperation.password_change,
        {"username": "admin", "password": "FirstSecret", "level": 15},
    )
    public_hash = command_hash(dry_run_commands)
    state.save_dry_run(
        {
            "device_id": device.id,
            "operation": "password_change",
            "command_hash": public_hash,
            "private_command_hash": private_command_hash(dry_run_commands, secret_key="excel-lab-secret-key"),
        }
    )
    state.save_backup(device.id, "hostname sw1\nusername admin secret <redacted>", {"config_hash": "safe"})
    _save_matching_validation(state, device, "password_change")
    service = ExcelLabSafetyService(
        state,
        vault,
        settings=Settings(
            environment="test",
            secret_key="excel-lab-secret-key",
            lab_device_allowlist=device.ip_address,
        ),
    )

    decision, _runtime = service.evaluate(
        ExcelLabSafetyRequest(
            device=device,
            operation=VendorOperation.password_change,
            credential_ref="lab-admin",
            command_parameters={"username": "admin", "password": "SecondSecret", "level": 15},
            simulation_hash=public_hash,
        )
    )

    assert command_hash(dry_run_commands) == public_hash
    assert decision.allowed is False
    assert "simulation_hash" in decision.denied_gates


def test_excel_lab_safety_blocks_unknown_qtech_and_eltex_config_apply(tmp_path: Path, monkeypatch) -> None:
    unknown, qtech, eltex = load_excel_inventory(
        write_inventory(
            tmp_path / "inventory.xlsx",
            [
                ["Active", "unknown", "Unknown SNMP Product", "192.0.2.71", "Huawei", "Switch", "Lab", "NetOps"],
                ["Active", "qtech", "QSW-4610", "192.0.2.72", "QTECH", "Switch", "Lab", "NetOps"],
                ["Active", "eltex", "MES2448", "192.0.2.73", "Eltex", "Switch", "Lab", "NetOps"],
            ],
        )
    )
    state, vault = _state_with_secret(tmp_path, monkeypatch)
    service = ExcelLabSafetyService(
        state,
        vault,
        settings=Settings(environment="test", secret_key="excel-lab-secret-key", lab_device_allowlist="192.0.2.71,192.0.2.72,192.0.2.73"),
    )

    for device in (unknown, qtech, eltex):
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
