from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.core.transport_strategy import DeviceFamily
from app.core.vendor_driver_contracts import VendorOperation
from app.services.file_credential_vault import FileCredentialVault
from app.services.file_lab_state import FileLabState
from app.services.vendor_command_templates import VendorCommandTemplateService, command_hash
from tests.enterprise.excel_lab_helpers import write_inventory


def test_excel_lab_certification_records_are_lab_only(tmp_path: Path) -> None:
    state = FileLabState(tmp_path / ".switchfleet_lab")
    record = state.save_lab_validation(
        {
            "device_id": "dev1",
            "device_label": "sw1-lab",
            "capability": "backup",
            "production_certified": True,
            "evidence": "manual lab check",
        }
    )

    assert record["status"] == "approved"
    assert record["production_certified"] is False
    assert state.latest_validation_for("dev1", "backup") is not None


def test_excel_lab_certify_requires_backup_and_dry_run(tmp_path: Path, monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(tmp_path / "inventory.xlsx")
    state = FileLabState(tmp_path / ".switchfleet_lab")
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    FileCredentialVault(state).create_or_update(name="lab-admin", username="admin", secret="VaultSecret")
    device = __import__("app.services.excel_inventory", fromlist=["load_excel_inventory"]).load_excel_inventory(inventory)[0]
    env = os.environ.copy()
    env["NCP_SECRET_KEY"] = "excel-lab-secret-key"
    env["NCP_LAB_DEVICE_ALLOWLIST"] = device.ip_address

    missing_dry_run = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            "--state-dir",
            str(state.paths.root),
            str(inventory),
            "certify",
            "--device",
            device.ip_address,
            "--capability",
            "vlan_create",
            "--credential",
            "lab-admin",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_dry_run.returncode != 0
    assert "backup is required" in missing_dry_run.stderr

    commands = VendorCommandTemplateService().render(DeviceFamily.cisco_ios, VendorOperation.vlan_create, {"vlan_id": 123, "name": "TEST"})
    state.save_backup(device.id, "hostname sw1", {"config_hash": "safe"})
    state.save_dry_run({"device_id": device.id, "operation": "vlan_create", "command_hash": command_hash(commands)})
    certified = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            "--state-dir",
            str(state.paths.root),
            str(inventory),
            "certify",
            "--device",
            device.ip_address,
            "--capability",
            "vlan_create",
            "--credential",
            "lab-admin",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert certified.returncode == 0, certified.stderr
    assert '"capability": "vlan_create"' in certified.stdout


def test_excel_lab_certify_rejects_qtech_config_apply(tmp_path: Path, monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(
        tmp_path / "inventory.xlsx",
        [["Active", "qtech", "QSW-4610", "10.13.4.72", "QTECH", "Switch", "Lab", "NetOps"]],
    )
    state = FileLabState(tmp_path / ".switchfleet_lab")
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    FileCredentialVault(state).create_or_update(name="lab-admin", username="admin", secret="VaultSecret")
    env = os.environ.copy()
    env["NCP_SECRET_KEY"] = "excel-lab-secret-key"
    env["NCP_LAB_DEVICE_ALLOWLIST"] = "10.13.4.72"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            "--state-dir",
            str(state.paths.root),
            str(inventory),
            "certify",
            "--device",
            "qtech",
            "--capability",
            "vlan_create",
            "--credential",
            "lab-admin",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "qtech cannot be certified for config apply" in result.stderr


def test_excel_lab_certify_password_change_requires_private_dry_run_hash(tmp_path: Path, monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(tmp_path / "inventory.xlsx")
    state = FileLabState(tmp_path / ".switchfleet_lab")
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    FileCredentialVault(state).create_or_update(name="lab-admin", username="admin", secret="VaultSecret")
    device = __import__("app.services.excel_inventory", fromlist=["load_excel_inventory"]).load_excel_inventory(inventory)[0]
    commands = VendorCommandTemplateService().render(
        DeviceFamily.cisco_ios,
        VendorOperation.password_change,
        {"username": "admin", "password": "DryRunSecret123", "level": 15},
    )
    state.save_backup(device.id, "hostname sw1", {"config_hash": "safe"})
    state.save_dry_run({"device_id": device.id, "operation": "password_change", "command_hash": command_hash(commands)})
    env = os.environ.copy()
    env["NCP_SECRET_KEY"] = "excel-lab-secret-key"
    env["NCP_LAB_DEVICE_ALLOWLIST"] = device.ip_address

    result = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            "--state-dir",
            str(state.paths.root),
            str(inventory),
            "certify",
            "--device",
            device.ip_address,
            "--capability",
            "password_change",
            "--credential",
            "lab-admin",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "stored dry-run" in result.stderr
