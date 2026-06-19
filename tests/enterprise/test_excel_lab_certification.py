from __future__ import annotations

import os
import json
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


def test_excel_lab_backup_certification_requires_a_fresh_captured_backup(tmp_path: Path, monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(tmp_path / "inventory.xlsx")
    state = FileLabState(tmp_path / ".switchfleet_lab")
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    FileCredentialVault(state).create_or_update(name="lab-admin", username="admin", secret="VaultSecret")
    device = __import__("app.services.excel_inventory", fromlist=["load_excel_inventory"]).load_excel_inventory(inventory)[0]
    env = os.environ.copy()
    env["NCP_SECRET_KEY"] = "excel-lab-secret-key"
    env["NCP_LAB_DEVICE_ALLOWLIST"] = device.ip_address
    command = [
        sys.executable,
        "scripts/excel_lab.py",
        "--state-dir",
        str(state.paths.root),
        str(inventory),
        "certify",
        "--device",
        device.ip_address,
        "--capability",
        "backup",
        "--credential",
        "lab-admin",
    ]

    missing = subprocess.run(command, cwd=repo_root, env=env, capture_output=True, text=True, check=False)
    assert missing.returncode != 0
    assert "fresh sanitized backup" in missing.stderr

    state.save_backup(device.id, "hostname sw1", {"source": "unit"})
    certified = subprocess.run(command, cwd=repo_root, env=env, capture_output=True, text=True, check=False)
    assert certified.returncode == 0, certified.stderr
    assert '"capability": "read_backup"' in certified.stdout


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
    hash_value = command_hash(commands)
    state.save_backup(device.id, "hostname sw1", {"config_hash": "safe"})
    state.save_dry_run({"device_id": device.id, "operation": "vlan_create", "command_hash": hash_value})
    missing_evaluation = subprocess.run(
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
    assert missing_evaluation.returncode != 0
    assert "Run evaluate-apply" in missing_evaluation.stderr

    evaluated = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            "--state-dir",
            str(state.paths.root),
            str(inventory),
            "evaluate-apply",
            "--device",
            device.ip_address,
            "--credential",
            "lab-admin",
            "--operation",
            "vlan_create",
            "--vlan-id",
            "123",
            "--name",
            "TEST",
            "--simulation-hash",
            hash_value,
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert evaluated.returncode == 0, evaluated.stderr
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
    assert '"family": "cisco_ios"' in certified.stdout
    assert '"selected_transport": "netmiko"' in certified.stdout


def test_excel_lab_certify_rejects_qtech_config_apply(tmp_path: Path, monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(
        tmp_path / "inventory.xlsx",
        [["Active", "qtech", "QSW-4610", "192.0.2.72", "QTECH", "Switch", "Lab", "NetOps"]],
    )
    state = FileLabState(tmp_path / ".switchfleet_lab")
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    FileCredentialVault(state).create_or_update(name="lab-admin", username="admin", secret="VaultSecret")
    env = os.environ.copy()
    env["NCP_SECRET_KEY"] = "excel-lab-secret-key"
    env["NCP_LAB_DEVICE_ALLOWLIST"] = "192.0.2.72"

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


def test_excel_lab_certify_requires_matching_evaluation_credential_and_runtime(tmp_path: Path, monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(tmp_path / "inventory.xlsx")
    state = FileLabState(tmp_path / ".switchfleet_lab")
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    vault = FileCredentialVault(state)
    vault.create_or_update(name="lab-admin", username="admin", secret="VaultSecret")
    vault.create_or_update(name="other-admin", username="admin", secret="OtherSecret")
    device = __import__("app.services.excel_inventory", fromlist=["load_excel_inventory"]).load_excel_inventory(inventory)[0]
    env = os.environ.copy()
    env["NCP_SECRET_KEY"] = "excel-lab-secret-key"
    env["NCP_LAB_DEVICE_ALLOWLIST"] = device.ip_address
    commands = VendorCommandTemplateService().render(DeviceFamily.cisco_ios, VendorOperation.vlan_create, {"vlan_id": 123, "name": "TEST"})
    hash_value = command_hash(commands)
    state.save_backup(device.id, "hostname sw1", {"config_hash": "safe"})
    state.save_dry_run({"device_id": device.id, "operation": "vlan_create", "command_hash": hash_value})

    evaluated = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            "--state-dir",
            str(state.paths.root),
            str(inventory),
            "evaluate-apply",
            "--device",
            device.ip_address,
            "--credential",
            "lab-admin",
            "--operation",
            "vlan_create",
            "--vlan-id",
            "123",
            "--name",
            "TEST",
            "--simulation-hash",
            hash_value,
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert evaluated.returncode == 0, evaluated.stderr

    wrong_credential = subprocess.run(
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
            "other-admin",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert wrong_credential.returncode != 0
    assert "Run evaluate-apply" in wrong_credential.stderr

    stored = json.loads(state.paths.evaluations.read_text(encoding="utf-8"))
    stored["evaluations"][0]["driver_family"] = "huawei_vrp"
    state.paths.evaluations.write_text(json.dumps(stored), encoding="utf-8")
    stale_runtime = subprocess.run(
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
    assert stale_runtime.returncode != 0
    assert "Run evaluate-apply" in stale_runtime.stderr

    stored["evaluations"][0]["driver_family"] = "cisco_ios"
    stored["evaluations"][0]["driver_name"] = "StaleDriver"
    state.paths.evaluations.write_text(json.dumps(stored), encoding="utf-8")
    stale_driver = subprocess.run(
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
    assert stale_driver.returncode != 0
    assert "Run evaluate-apply" in stale_driver.stderr


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


def test_excel_lab_certify_password_change_requires_matching_private_evaluation(tmp_path: Path, monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(tmp_path / "inventory.xlsx")
    state = FileLabState(tmp_path / ".switchfleet_lab")
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    FileCredentialVault(state).create_or_update(name="lab-admin", username="admin", secret="VaultSecret")
    device = __import__("app.services.excel_inventory", fromlist=["load_excel_inventory"]).load_excel_inventory(inventory)[0]
    state.save_backup(device.id, "hostname sw1", {"config_hash": "safe"})
    env = os.environ.copy()
    env["NCP_SECRET_KEY"] = "excel-lab-secret-key"
    env["NCP_LAB_DEVICE_ALLOWLIST"] = device.ip_address

    def run(args: list[str], *, password: str | None = None) -> subprocess.CompletedProcess[str]:
        local_env = env.copy()
        if password is not None:
            local_env["SWITCHFLEET_NEW_PASSWORD"] = password
        return subprocess.run(
            [sys.executable, "scripts/excel_lab.py", "--state-dir", str(state.paths.root), str(inventory), *args],
            cwd=repo_root,
            env=local_env,
            capture_output=True,
            text=True,
            check=False,
        )

    first_dry_run = run(
        [
            "dry-run",
            "--device",
            device.ip_address,
            "--operation",
            "password_change",
            "--username",
            "admin",
            "--new-password-env",
            "SWITCHFLEET_NEW_PASSWORD",
            "--level",
            "15",
        ],
        password="FirstSecret123",
    )
    assert first_dry_run.returncode == 0, first_dry_run.stderr
    public_hash = json.loads(first_dry_run.stdout)["command_hash"]
    first_eval = run(
        [
            "evaluate-apply",
            "--device",
            device.ip_address,
            "--credential",
            "lab-admin",
            "--operation",
            "password_change",
            "--username",
            "admin",
            "--new-password-env",
            "SWITCHFLEET_NEW_PASSWORD",
            "--level",
            "15",
            "--simulation-hash",
            public_hash,
        ],
        password="FirstSecret123",
    )
    assert first_eval.returncode == 0, first_eval.stderr

    second_dry_run = run(
        [
            "dry-run",
            "--device",
            device.ip_address,
            "--operation",
            "password_change",
            "--username",
            "admin",
            "--new-password-env",
            "SWITCHFLEET_NEW_PASSWORD",
            "--level",
            "15",
        ],
        password="SecondSecret456",
    )
    assert second_dry_run.returncode == 0, second_dry_run.stderr
    assert json.loads(second_dry_run.stdout)["command_hash"] == public_hash

    stale_evaluation = run(
        ["certify", "--device", device.ip_address, "--capability", "password_change", "--credential", "lab-admin"]
    )
    assert stale_evaluation.returncode != 0
    assert "Run evaluate-apply" in stale_evaluation.stderr

    second_eval = run(
        [
            "evaluate-apply",
            "--device",
            device.ip_address,
            "--credential",
            "lab-admin",
            "--operation",
            "password_change",
            "--username",
            "admin",
            "--new-password-env",
            "SWITCHFLEET_NEW_PASSWORD",
            "--level",
            "15",
            "--simulation-hash",
            public_hash,
        ],
        password="SecondSecret456",
    )
    assert second_eval.returncode == 0, second_eval.stderr
    certified = run(["certify", "--device", device.ip_address, "--capability", "password_change", "--credential", "lab-admin"])

    assert certified.returncode == 0, certified.stderr
    state_text = "\n".join(path.read_text(encoding="utf-8") for path in state.paths.root.rglob("*") if path.is_file())
    assert "FirstSecret123" not in state_text
    assert "SecondSecret456" not in state_text
