from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

from app.services.excel_inventory import load_excel_inventory
from app.services.file_lab_state import FileLabState
from tests.enterprise.excel_lab_helpers import write_inventory


REAL_INVENTORY_MODELS_CSV = Path(__file__).resolve().parents[1] / "fixtures" / "real_inventory_models.csv"


def real_inventory_rows() -> list[list[str]]:
    with REAL_INVENTORY_MODELS_CSV.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        next(reader)
        return [row for row in reader]


def test_excel_lab_cli_help_and_doctor_without_db(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(tmp_path / "inventory.xlsx")
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["NCP_SECRET_KEY"] = "excel-lab-secret-key"
    help_result = subprocess.run(
        [sys.executable, "scripts/excel_lab.py", "--help"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    doctor_result = subprocess.run(
        [sys.executable, "scripts/excel_lab.py", str(inventory), "doctor"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert help_result.returncode == 0, help_result.stderr
    assert "Excel-first" in help_result.stdout
    assert doctor_result.returncode == 0, doctor_result.stderr
    assert '"database_required": false' in doctor_result.stdout


def test_switchfleet_console_entrypoint_targets_excel_first_cli() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    module_help = subprocess.run(
        [sys.executable, "-m", "scripts.excel_lab", "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert 'switchfleet = "scripts.excel_lab:main"' in pyproject
    assert 'include = ["app*", "netops_orchestrator*", "scripts*"]' in pyproject
    assert module_help.returncode == 0, module_help.stderr
    assert "usage: switchfleet" in module_help.stdout
    assert "Excel-first SwitchFleet local admin CLI" in module_help.stdout
    assert module_help.stdout.index("evaluate-apply") < module_help.stdout.index("certify") < module_help.stdout.index("execute-apply")


def test_release_bundle_switchfleet_wrappers_target_excel_first_cli() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    build_script = (repo_root / "scripts" / "build-release-bundles.ps1").read_text(encoding="utf-8")

    assert "-m scripts.excel_lab" in build_script
    assert "-m netops_orchestrator.cli" not in build_script
    assert "$LocalRuntimeRequirements" in build_script
    assert '"fastapi>=0.115"' not in build_script
    assert '"sqlalchemy>=2.0"' not in build_script
    assert '"alembic>=1.13"' not in build_script
    assert "switchfleet-api" not in build_script
    assert 'Copy-Item -LiteralPath (Join-Path $RepoRoot "examples")' in build_script
    assert 'Copy-Item -LiteralPath (Join-Path $RepoRoot "scripts")' in build_script


def test_pyproject_core_dependencies_exclude_enterprise_runtime() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    core_dependencies = pyproject.split("dependencies = [", 1)[1].split("\n]\n\n[project.optional-dependencies]", 1)[0]
    enterprise_extra = pyproject.split("enterprise = [", 1)[1].split("\n]", 1)[0]

    for package in ("fastapi", "sqlalchemy", "alembic", "psycopg", "redis", "celery", "uvicorn"):
        assert package not in core_dependencies
        assert package in enterprise_extra
    assert "switchfleet = \"scripts.excel_lab:main\"" in pyproject


def test_excel_lab_cli_list_runs_from_excel(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(tmp_path / "inventory.xlsx")
    result = subprocess.run(
        [sys.executable, "scripts/excel_lab.py", str(inventory), "list"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "sw1-lab" in result.stdout
    assert "cisco_ios" in result.stdout
    payload = json.loads(result.stdout)
    first = payload["devices"][0]
    assert first["device_ip"] == "192.0.2.67"
    assert first["ip_address"] == "192.0.2.67"
    assert first["vendor"] == "Cisco"
    assert first["model"] == "Catalyst 2960"
    assert first["family"] == "cisco_ios"
    assert first["selected_transport"] == "netmiko"
    assert first["backup_supported"] is True
    assert first["apply_support_level"] == "lab_apply_candidate"
    assert "id" not in first
    assert "internal_device_id" not in first


def test_excel_lab_cli_allowlisted_only_uses_ip_not_internal_id(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(tmp_path / "inventory.xlsx")
    device = load_excel_inventory(inventory)[0]
    env = os.environ.copy()

    env["NCP_LAB_DEVICE_ALLOWLIST"] = device.ip_address
    by_ip = subprocess.run(
        [sys.executable, "scripts/excel_lab.py", str(inventory), "list", "--allowlisted-only"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    env["NCP_LAB_DEVICE_ALLOWLIST"] = device.id
    by_internal = subprocess.run(
        [sys.executable, "scripts/excel_lab.py", str(inventory), "list", "--allowlisted-only"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert by_ip.returncode == 0, by_ip.stderr
    by_ip_devices = json.loads(by_ip.stdout)["devices"]
    assert [item["device_ip"] for item in by_ip_devices] == [device.ip_address]
    assert by_ip_devices[0]["lab_allowed"] is True
    assert "internal_device_id" not in by_ip_devices[0]
    assert by_internal.returncode == 0, by_internal.stderr
    assert json.loads(by_internal.stdout)["devices"] == []


def test_excel_lab_cli_summary_allowlist_count_uses_ip_not_internal_id(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(tmp_path / "inventory.xlsx")
    device = load_excel_inventory(inventory)[0]
    env = os.environ.copy()

    env["NCP_LAB_DEVICE_ALLOWLIST"] = device.ip_address
    by_ip = subprocess.run(
        [sys.executable, "scripts/excel_lab.py", str(inventory), "summary"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    env["NCP_LAB_DEVICE_ALLOWLIST"] = device.id
    by_internal = subprocess.run(
        [sys.executable, "scripts/excel_lab.py", str(inventory), "summary"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert by_ip.returncode == 0, by_ip.stderr
    assert json.loads(by_ip.stdout)["allowlisted_count"] == 1
    assert by_internal.returncode == 0, by_internal.stderr
    assert json.loads(by_internal.stdout)["allowlisted_count"] == 0


def test_excel_lab_cli_device_selector_is_ip_first(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(tmp_path / "inventory.xlsx")
    device = load_excel_inventory(inventory)[0]

    by_ip = subprocess.run(
        [sys.executable, "scripts/excel_lab.py", str(inventory), "check-runtime", "--ip", device.ip_address],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    by_label = subprocess.run(
        [sys.executable, "scripts/excel_lab.py", str(inventory), "check-runtime", "--device", device.label],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    unknown = subprocess.run(
        [sys.executable, "scripts/excel_lab.py", str(inventory), "check-runtime", "--device", "192.0.2.250"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    by_internal = subprocess.run(
        [sys.executable, "scripts/excel_lab.py", str(inventory), "check-runtime", "--device", device.id],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert by_ip.returncode == 0, by_ip.stderr
    assert json.loads(by_ip.stdout)["device_ip"] == device.ip_address
    assert by_label.returncode != 0
    assert "Use the device IP address" in by_label.stderr
    assert unknown.returncode != 0
    assert "Device IP '192.0.2.250' was not found" in unknown.stderr
    assert by_internal.returncode == 0, by_internal.stderr
    internal_payload = json.loads(by_internal.stdout)
    assert internal_payload["selector_warning"] == "Internal device IDs are deprecated for CLI use; use IP address instead."
    assert internal_payload["device_ip"] == device.ip_address


def test_excel_lab_cli_duplicate_ip_fails_closed(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(
        tmp_path / "inventory.xlsx",
        [
            ["Active", "switch-a", "Catalyst 2960", "192.0.2.67", "Cisco", "Switch", "Lab", "NetOps"],
            ["Active", "switch-b", "Catalyst 2960", "192.0.2.67", "Cisco", "Switch", "Lab", "NetOps"],
        ],
    )
    result = subprocess.run(
        [sys.executable, "scripts/excel_lab.py", str(inventory), "check-runtime", "--device", "192.0.2.67"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Duplicate IP address" in result.stderr
    assert "switch-a" in result.stderr
    assert "switch-b" in result.stderr


def test_excel_lab_cli_all_runtime_and_dry_run_cover_every_excel_device(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(
        tmp_path / "inventory.xlsx",
        [
            ["Active", "cisco-lab", "Catalyst 2960", "192.0.2.67", "Cisco", "Switch", "Lab", "NetOps"],
            ["Active", "huawei-lab", "S5735", "192.0.2.68", "Huawei", "Switch", "Lab", "NetOps"],
        ],
    )
    state_dir = tmp_path / ".switchfleet_lab"

    runtime = subprocess.run(
        [sys.executable, "scripts/excel_lab.py", "--state-dir", str(state_dir), str(inventory), "check-runtime", "--all"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    dry_run = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            "--state-dir",
            str(state_dir),
            str(inventory),
            "dry-run",
            "--all",
            "--operation",
            "vlan_create",
            "--vlan-id",
            "123",
            "--name",
            "TEST",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert runtime.returncode == 0, runtime.stderr
    runtime_payload = json.loads(runtime.stdout)
    assert [item["device_ip"] for item in runtime_payload["devices"]] == ["192.0.2.67", "192.0.2.68"]
    assert {item["family"] for item in runtime_payload["devices"]} == {"cisco_ios", "huawei_vrp"}
    assert "internal_device_id" not in json.dumps(runtime_payload)

    assert dry_run.returncode == 0, dry_run.stderr
    dry_run_payload = json.loads(dry_run.stdout)
    assert [item["status"] for item in dry_run_payload["results"]] == ["ok", "ok"]
    assert [item["device_ip"] for item in dry_run_payload["results"]] == ["192.0.2.67", "192.0.2.68"]
    assert all(item["command_hash"] for item in dry_run_payload["results"])
    stored = json.loads((state_dir / "dry_runs.json").read_text(encoding="utf-8"))["dry_runs"]
    assert sorted(item["device_ip"] for item in stored) == ["192.0.2.67", "192.0.2.68"]


def test_excel_lab_cli_all_evaluate_uses_latest_per_device_dry_run_hash(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(
        tmp_path / "inventory.xlsx",
        [
            ["Active", "cisco-lab", "Catalyst 2960", "192.0.2.67", "Cisco", "Switch", "Lab", "NetOps"],
            ["Active", "huawei-lab", "S5735", "192.0.2.68", "Huawei", "Switch", "Lab", "NetOps"],
        ],
    )
    state_dir = tmp_path / ".switchfleet_lab"
    env = os.environ.copy()
    env["NCP_SECRET_KEY"] = "excel-lab-secret-key"
    env["SWITCHFLEET_TEST_PASSWORD"] = "VaultSecret"

    add_credential = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            "--state-dir",
            str(state_dir),
            str(inventory),
            "add-credential",
            "--name",
            "lab-admin",
            "--username",
            "admin",
            "--password-env",
            "SWITCHFLEET_TEST_PASSWORD",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    dry_run = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            "--state-dir",
            str(state_dir),
            str(inventory),
            "dry-run",
            "--all",
            "--operation",
            "vlan_create",
            "--vlan-id",
            "123",
            "--name",
            "TEST",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    evaluate = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            "--state-dir",
            str(state_dir),
            str(inventory),
            "evaluate-apply",
            "--all",
            "--credential",
            "lab-admin",
            "--operation",
            "vlan_create",
            "--vlan-id",
            "123",
            "--name",
            "TEST",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert add_credential.returncode == 0, add_credential.stderr
    assert dry_run.returncode == 0, dry_run.stderr
    dry_hashes = {item["device_ip"]: item["command_hash"] for item in json.loads(dry_run.stdout)["results"]}
    assert evaluate.returncode == 0, evaluate.stderr
    results = json.loads(evaluate.stdout)["results"]
    assert [item["status"] for item in results] == ["ok", "ok"]
    assert {item["device_ip"]: item["command_hash"] for item in results} == dry_hashes
    assert all("fresh_backup" in item["denied_gates"] for item in results)


def test_excel_lab_cli_profile_drives_bulk_dry_run_and_evaluate(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(
        tmp_path / "inventory.xlsx",
        [
            ["Active", "cisco-lab", "Catalyst 2960", "192.0.2.67", "Cisco", "Switch", "Lab", "NetOps"],
            ["Active", "huawei-lab", "S5735", "192.0.2.68", "Huawei", "Switch", "Lab", "NetOps"],
        ],
    )
    profile = tmp_path / "vlan-profile.json"
    profile.write_text(
        json.dumps(
            {
                "operation": "vlan_create",
                "credential": "lab-admin",
                "parameters": {"vlan_id": 321, "name": "PROFILE_VLAN"},
            }
        ),
        encoding="utf-8",
    )
    state_dir = tmp_path / ".switchfleet_lab"
    env = os.environ.copy()
    env["NCP_SECRET_KEY"] = "excel-lab-secret-key"
    env["SWITCHFLEET_TEST_PASSWORD"] = "VaultSecret"

    add_credential = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            "--state-dir",
            str(state_dir),
            str(inventory),
            "add-credential",
            "--name",
            "lab-admin",
            "--username",
            "admin",
            "--password-env",
            "SWITCHFLEET_TEST_PASSWORD",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    dry_run = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            "--state-dir",
            str(state_dir),
            str(inventory),
            "dry-run",
            "--all",
            "--profile",
            str(profile),
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    evaluate = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            "--state-dir",
            str(state_dir),
            str(inventory),
            "evaluate-apply",
            "--all",
            "--profile",
            str(profile),
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert add_credential.returncode == 0, add_credential.stderr
    assert dry_run.returncode == 0, dry_run.stderr
    dry_payload = json.loads(dry_run.stdout)
    assert [item["status"] for item in dry_payload["results"]] == ["ok", "ok"]
    rendered = json.dumps(dry_payload)
    assert "vlan 321" in rendered
    assert "PROFILE_VLAN" in rendered
    assert evaluate.returncode == 0, evaluate.stderr
    eval_payload = json.loads(evaluate.stdout)
    assert [item["status"] for item in eval_payload["results"]] == ["ok", "ok"]
    assert {item["operation"] for item in eval_payload["results"]} == {"vlan_create"}


def test_excel_lab_cli_workflow_runs_profile_for_all_devices_without_real_apply(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(
        tmp_path / "inventory.xlsx",
        [
            ["Active", "cisco-lab", "Catalyst 2960", "192.0.2.67", "Cisco", "Switch", "Lab", "NetOps"],
            ["Active", "huawei-lab", "S5735", "192.0.2.68", "Huawei", "Switch", "Lab", "NetOps"],
        ],
    )
    profile = tmp_path / "vlan-profile.json"
    profile.write_text(
        json.dumps(
            {
                "operation": "vlan_create",
                "credential": "lab-admin",
                "parameters": {"vlan_id": 321, "name": "PROFILE_VLAN"},
            }
        ),
        encoding="utf-8",
    )
    state_dir = tmp_path / ".switchfleet_lab"
    env = os.environ.copy()
    env["NCP_SECRET_KEY"] = "excel-lab-secret-key"
    env["SWITCHFLEET_TEST_PASSWORD"] = "VaultSecret"

    add_credential = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            "--state-dir",
            str(state_dir),
            str(inventory),
            "add-credential",
            "--name",
            "lab-admin",
            "--username",
            "admin",
            "--password-env",
            "SWITCHFLEET_TEST_PASSWORD",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    workflow = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            "--state-dir",
            str(state_dir),
            str(inventory),
            "workflow",
            "--profile",
            str(profile),
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert add_credential.returncode == 0, add_credential.stderr
    assert workflow.returncode == 0, workflow.stderr
    payload = json.loads(workflow.stdout)
    assert payload["workflow"]["real_apply_executed"] is False
    assert payload["workflow"]["credential_ref"] == "lab-admin"
    assert payload["workflow"]["parameters"] == {"name": "PROFILE_VLAN", "vlan_id": 321}
    assert payload["workflow"]["backup"] == {"skipped": 2}
    assert payload["workflow"]["dry_run"] == {"ok": 2}
    assert payload["workflow"]["evaluate"] == {"ok": 2}
    assert [item["device_ip"] for item in payload["results"]] == ["192.0.2.67", "192.0.2.68"]
    assert all(item["dry_run_status"] == "ok" for item in payload["results"])
    assert all(item["evaluate_status"] == "ok" for item in payload["results"])
    assert all(item["command_hash"] for item in payload["results"])
    report = payload["workflow"]["report"]
    markdown_path = state_dir / report["markdown_path"]
    json_path = state_dir / report["json_path"]
    assert report["kind"] == "workflow"
    assert markdown_path.exists()
    assert json_path.exists()
    markdown = markdown_path.read_text(encoding="utf-8")
    report_payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "192.0.2.67" in markdown
    assert "192.0.2.68" in markdown
    assert "vlan_create" in markdown
    assert "vlan_id=321" in markdown
    assert "name=PROFILE_VLAN" in markdown
    assert "VaultSecret" not in markdown
    assert "VaultSecret" not in json.dumps(report_payload)
    assert report_payload["payload"]["workflow"]["real_apply_executed"] is False
    assert report_payload["payload"]["workflow"]["credential_ref"] == "lab-admin"
    assert report_payload["payload"]["workflow"]["credential"] == "<redacted>"


def test_excel_lab_cli_packaged_example_workflow_covers_all_vendors_without_real_apply(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = repo_root / "examples" / "lab" / "inventory.example.xlsx"
    profile = repo_root / "examples" / "lab" / "vlan-profile.example.json"
    state_dir = tmp_path / ".switchfleet_lab"

    workflow = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            "--state-dir",
            str(state_dir),
            str(inventory),
            "workflow",
            "--profile",
            str(profile),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert workflow.returncode == 0, workflow.stderr
    payload = json.loads(workflow.stdout)
    assert payload["workflow"]["device_count"] == 12
    assert payload["workflow"]["parameters"] == {"name": "TEST_VLAN", "vlan_id": 123}
    assert payload["workflow"]["real_apply_executed"] is False
    assert payload["workflow"]["backup"] == {"skipped": 12}
    assert payload["workflow"]["dry_run"]["ok"] >= 5
    assert payload["workflow"]["evaluate"]["ok"] >= 5
    results_by_label = {item["label"]: item for item in payload["results"]}
    assert set(results_by_label) == {
        "huawei-s5735",
        "hpe-1910",
        "hpe-2530",
        "qtech-4610",
        "eltex-2324",
        "bulat-bs2500",
        "dell-3524",
        "cisco-2960",
        "dlink-des1100",
        "continent-500",
        "unknown-snmp",
        "icmp-only",
    }
    for label in ("huawei-s5735", "hpe-1910", "hpe-2530", "dell-3524", "cisco-2960"):
        assert results_by_label[label]["dry_run_status"] == "ok"
        assert results_by_label[label]["evaluate_status"] == "ok"
        assert results_by_label[label]["command_hash"]
    for label in (
        "qtech-4610",
        "eltex-2324",
        "bulat-bs2500",
        "dlink-des1100",
        "continent-500",
        "unknown-snmp",
        "icmp-only",
    ):
        assert results_by_label[label]["dry_run_status"] == "failed"
        assert results_by_label[label]["evaluate_status"] == "failed"
        assert results_by_label[label]["error"]
    assert "excel-" not in json.dumps(payload)
    markdown_path = state_dir / payload["workflow"]["report"]["markdown_path"]
    assert markdown_path.exists()
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "192.0.2.10" in markdown
    assert "qtech-4610" in markdown
    assert "Bulk real-lab execution is intentionally disabled" in markdown


def test_excel_lab_cli_real_inventory_model_fixture_workflow_does_not_abort_on_any_vendor(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(tmp_path / "real-inventory.xlsx", real_inventory_rows())
    profile = repo_root / "examples" / "lab" / "vlan-profile.example.json"
    state_dir = tmp_path / ".switchfleet_lab"

    workflow = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            "--state-dir",
            str(state_dir),
            str(inventory),
            "workflow",
            "--profile",
            str(profile),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert workflow.returncode == 0, workflow.stderr
    payload = json.loads(workflow.stdout)
    results = payload["results"]
    labels = {item["label"] for item in results}

    assert payload["workflow"]["device_count"] == len(real_inventory_rows())
    assert payload["workflow"]["parameters"] == {"name": "TEST_VLAN", "vlan_id": 123}
    assert payload["workflow"]["real_apply_executed"] is False
    assert len(results) == len(real_inventory_rows())
    assert {
        "huawei-s5735",
        "huawei-ce6855",
        "3com-s4210",
        "hpe-2530",
        "qtech-4610",
        "eltex-2448",
        "bulat-bk",
        "dell-3524",
        "cisco-37xx",
        "dlink-des1100",
        "continent-500",
        "unknown-snmp",
        "icmp-only",
    }.issubset(labels)
    assert any(item["dry_run_status"] == "ok" for item in results)
    assert any(item["dry_run_status"] == "failed" for item in results)
    assert all(item["device_ip"].startswith("192.0.2.") for item in results)
    assert "excel-" not in json.dumps(payload)
    assert payload["workflow"]["allowed_count"] == 0
    assert (state_dir / payload["workflow"]["report"]["markdown_path"]).exists()


def test_excel_lab_cli_workflow_with_backup_reports_per_device_failures_without_stopping(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(
        tmp_path / "inventory.xlsx",
        [
            ["Active", "cisco-lab", "Catalyst 2960", "192.0.2.67", "Cisco", "Switch", "Lab", "NetOps"],
            ["Active", "huawei-lab", "S5735", "192.0.2.68", "Huawei", "Switch", "Lab", "NetOps"],
        ],
    )
    profile = tmp_path / "vlan-profile.json"
    profile.write_text(
        json.dumps(
            {
                "operation": "vlan_create",
                "credential": "lab-admin",
                "parameters": {"vlan_id": 321, "name": "PROFILE_VLAN"},
            }
        ),
        encoding="utf-8",
    )
    state_dir = tmp_path / ".switchfleet_lab"
    env = os.environ.copy()
    env["NCP_SECRET_KEY"] = "excel-lab-secret-key"
    env["SWITCHFLEET_TEST_PASSWORD"] = "VaultSecret"

    add_credential = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            "--state-dir",
            str(state_dir),
            str(inventory),
            "add-credential",
            "--name",
            "lab-admin",
            "--username",
            "admin",
            "--password-env",
            "SWITCHFLEET_TEST_PASSWORD",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    workflow = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            "--state-dir",
            str(state_dir),
            str(inventory),
            "workflow",
            "--profile",
            str(profile),
            "--with-backup",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert add_credential.returncode == 0, add_credential.stderr
    assert workflow.returncode == 0, workflow.stderr
    payload = json.loads(workflow.stdout)
    assert payload["workflow"]["backup"] == {"failed": 2}
    assert payload["workflow"]["dry_run"] == {"ok": 2}
    assert payload["workflow"]["evaluate"] == {"ok": 2}
    assert all("NCP_LAB_DEVICE_ALLOWLIST" in item["error"] for item in payload["results"])


def test_excel_lab_cli_bulk_real_lab_execute_is_blocked(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(tmp_path / "inventory.xlsx")
    result = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            str(inventory),
            "execute-apply",
            "--all",
            "--credential",
            "lab-admin",
            "--operation",
            "vlan_create",
            "--vlan-id",
            "123",
            "--name",
            "TEST",
            "--real-lab",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Bulk --all real lab execution is intentionally disabled" in result.stderr


def test_excel_lab_human_formatter_renders_device_table_without_internal_ids() -> None:
    from scripts.excel_lab import _format_human_result

    rendered = _format_human_result(
        "list",
        {
            "devices": [
                {
                    "device_ip": "192.0.2.67",
                    "label": "sw1",
                    "vendor": "Cisco",
                    "model": "Catalyst 2960",
                    "family": "cisco_ios",
                    "selected_transport": "netmiko",
                    "backup_status": "missing",
                    "apply_status": "candidate_gated",
                    "lab_allowed": True,
                    "internal_device_id": "excel-should-not-be-rendered",
                }
            ]
        },
    )

    assert "Excel inventory devices" in rendered
    assert "192.0.2.67" in rendered
    assert "cisco_ios" in rendered
    assert "excel-should-not-be-rendered" not in rendered


def test_excel_lab_workflow_public_parameters_redact_secret_values() -> None:
    from scripts.excel_lab import _public_parameters

    safe = _public_parameters({"username": "admin", "password": "SHOULD_NOT_LEAK", "vlan_id": 123})

    assert safe == {"password": "<redacted>", "username": "admin", "vlan_id": 123}


def test_excel_lab_human_workflow_output_shows_profile_parameters() -> None:
    from scripts.excel_lab import _format_human_result

    rendered = _format_human_result(
        "workflow",
        {
            "workflow": {
                "profile": "profile.json",
                "operation": "vlan_create",
                "credential": "lab-admin",
                "parameters": {"name": "TEST_VLAN", "vlan_id": 123},
                "with_backup": False,
                "device_count": 1,
                "backup": {"skipped": 1},
                "dry_run": {"ok": 1},
                "evaluate": {"ok": 1},
                "allowed_count": 0,
                "real_apply_executed": False,
                "report": {"markdown_path": "reports/workflow.md", "json_path": "reports/workflow.json"},
            },
            "results": [
                {
                    "device_ip": "192.0.2.67",
                    "label": "sw1",
                    "vendor": "Cisco",
                    "model": "Catalyst 2960",
                    "backup_status": "ok",
                    "dry_run_status": "ok",
                    "evaluate_status": "ok",
                    "allowed": True,
                    "command_hash": "abc123",
                    "next_execute_command": "switchfleet inventory.xlsx execute-apply --device 192.0.2.67 --profile profile.json --simulation-hash abc123 --real-lab",
                }
            ],
        },
    )

    assert "Parameters" in rendered
    assert "name=TEST_VLAN" in rendered
    assert "vlan_id=123" in rendered
    assert "Next execute commands" in rendered
    assert "execute-apply --device 192.0.2.67 --profile profile.json --simulation-hash abc123 --real-lab" in rendered


def test_excel_lab_next_execute_command_preserves_state_dir(tmp_path: Path) -> None:
    from argparse import Namespace
    from scripts.excel_lab import _next_execute_command

    inventory = write_inventory(
        tmp_path / "inventory.xlsx",
        [["Active", "sw1", "Catalyst 2960", "192.0.2.67", "Cisco", "Switch", "Lab", "NetOps"]],
    )
    device = load_excel_inventory(inventory)[0]
    state_dir = tmp_path / "custom-state"
    profile = tmp_path / "profile.json"
    command = _next_execute_command(
        Namespace(inventory_path=inventory, profile=profile, state_dir=state_dir),
        device,
        {"allowed": True, "command_hash": "abc123"},
    )

    assert command.startswith("switchfleet --state-dir ")
    assert f"--state-dir {state_dir}" in command
    assert f"{inventory} execute-apply" in command
    assert "--device 192.0.2.67" in command
    assert f"--profile {profile}" in command
    assert "--simulation-hash abc123 --real-lab" in command


def test_excel_lab_cli_human_flag_forces_operator_output_when_captured(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(
        tmp_path / "inventory.xlsx",
        [["Active", "sw1", "Catalyst 2960", "192.0.2.67", "Cisco", "Switch", "Lab", "NetOps"]],
    )

    result = subprocess.run(
        [sys.executable, "scripts/excel_lab.py", "--human", str(inventory), "list"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Excel inventory devices" in result.stdout
    assert "device_ip" in result.stdout
    assert "192.0.2.67" in result.stdout
    assert not result.stdout.lstrip().startswith("{")


def test_excel_lab_cli_summary_and_check_runtime_show_real_inventory_status(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(
        tmp_path / "inventory.xlsx",
        [
            ["Active", "qtech-lab", "QSW-4610", "192.0.2.67", "QTECH", "Switch", "Lab", "NetOps"],
            ["Active", "continent", "Continent-500", "192.0.2.68", "SecurityCode", "Security Appliance", "Lab", "SecOps"],
        ],
    )
    summary = subprocess.run(
        [sys.executable, "scripts/excel_lab.py", str(inventory), "summary"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    runtime = subprocess.run(
        [sys.executable, "scripts/excel_lab.py", str(inventory), "check-runtime", "--device", "192.0.2.67"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert summary.returncode == 0, summary.stderr
    assert '"vendors": {' in summary.stdout
    assert '"QTECH": 1' in summary.stdout
    assert '"SecurityCode": 1' in summary.stdout
    assert '"models": {' in summary.stdout
    assert '"QSW-4610": 1' in summary.stdout
    assert '"Continent-500": 1' in summary.stdout
    assert '"qtech": 1' in summary.stdout
    assert '"non_switch": 1' in summary.stdout
    assert '"unsupported_count": 1' in summary.stdout
    assert '"blocked_count": 1' in summary.stdout
    assert '"candidate_count": 0' in summary.stdout
    assert runtime.returncode == 0, runtime.stderr
    assert '"selector_used": "192.0.2.67"' in runtime.stdout
    assert '"device_ip": "192.0.2.67"' in runtime.stdout
    assert '"original_vendor": "QTECH"' in runtime.stdout
    assert '"normalized_vendor": "QTECH"' in runtime.stdout
    assert '"family": "qtech"' in runtime.stdout
    assert '"selected_transport": "custom_cli"' in runtime.stdout
    assert '"status": "blocked_until_certified"' in runtime.stdout
    assert "config_apply_allowed is false globally" in runtime.stdout


def test_excel_lab_cli_password_dry_run_stores_private_hash_without_plaintext(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(tmp_path / "inventory.xlsx")
    state_dir = tmp_path / ".switchfleet_lab"
    env = os.environ.copy()
    env["NCP_SECRET_KEY"] = "excel-lab-secret-key"
    env["SWITCHFLEET_NEW_PASSWORD"] = "DryRunSecret123"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/excel_lab.py",
            "--state-dir",
            str(state_dir),
            str(inventory),
            "dry-run",
            "--device",
            "192.0.2.67",
            "--operation",
            "password_change",
            "--username",
            "admin",
            "--new-password-env",
            "SWITCHFLEET_NEW_PASSWORD",
            "--level",
            "15",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "DryRunSecret123" not in result.stdout
    dry_runs_text = (state_dir / "dry_runs.json").read_text(encoding="utf-8")
    dry_runs = json.loads(dry_runs_text)["dry_runs"]
    assert "DryRunSecret123" not in dry_runs_text
    assert dry_runs[0]["private_command_hash"]


def test_excel_lab_cli_required_workflow_reaches_fake_execute_without_db_or_ssh(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(tmp_path / "inventory.xlsx")
    device = load_excel_inventory(inventory)[0]
    state_dir = tmp_path / ".switchfleet_lab"
    profile = tmp_path / "vlan-profile.json"
    profile.write_text(
        json.dumps(
            {
                "operation": "vlan_create",
                "credential": "lab-admin",
                "parameters": {"vlan_id": 123, "name": "TEST"},
            }
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["NCP_SECRET_KEY"] = "excel-lab-secret-key"
    env["NCP_LAB_DEVICE_ALLOWLIST"] = device.ip_address
    env["SWITCHFLEET_TEST_PASSWORD"] = "VaultSecret"

    def run(args: list[str], *, ok: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, "scripts/excel_lab.py", "--state-dir", str(state_dir), str(inventory), *args],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if ok:
            assert result.returncode == 0, result.stderr
        else:
            assert result.returncode != 0, result.stdout
        return result

    run(["doctor"])
    run(["summary"])
    run(["list"])
    run(["check-runtime", "--device", device.ip_address])
    run(["backup", "--device", device.ip_address, "--credential", "missing"], ok=False)
    run(["add-credential", "--name", "lab-admin", "--username", "admin", "--password-env", "SWITCHFLEET_TEST_PASSWORD"])
    dry_run = run(["dry-run", "--device", device.ip_address, "--operation", "vlan_create", "--vlan-id", "123", "--name", "TEST"])
    command_hash = json.loads(dry_run.stdout)["command_hash"]
    assert json.loads(dry_run.stdout)["device_ip"] == device.ip_address
    FileLabState(state_dir).save_backup(device.id, "hostname sw1\nusername admin secret SHOULD_NOT_LEAK", {"source": "unit"})
    before_cert = run(
        [
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
            command_hash,
        ]
    )
    before_payload = json.loads(before_cert.stdout)
    assert before_payload["device_ip"] == device.ip_address
    assert "device_id" not in before_payload
    assert "internal_device_id" not in before_payload
    assert "lab_validation" in before_payload["denied_gates"]
    certified = run(["certify", "--device", device.ip_address, "--capability", "vlan_create", "--credential", "lab-admin"])
    assert json.loads(certified.stdout)["device_ip"] == device.ip_address
    certification_report = run(["certification-report"])
    report_payload = json.loads(certification_report.stdout)
    report_text = json.dumps(report_payload)
    assert device.ip_address in report_text
    assert device.id not in report_text
    after_cert = run(
        [
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
            command_hash,
        ]
    )
    after_payload = json.loads(after_cert.stdout)
    assert after_payload["device_ip"] == device.ip_address
    assert "device_id" not in after_payload
    assert "internal_device_id" not in after_payload
    assert after_payload["allowed"] is True
    executed = run(
        [
            "execute-apply",
            "--device",
            device.ip_address,
            "--profile",
            str(profile),
            "--simulation-hash",
            command_hash,
        ]
    )
    executed_payload = json.loads(executed.stdout)
    assert executed_payload["device_ip"] == device.ip_address
    assert "device_id" not in executed_payload["decision"]
    assert "internal_device_id" not in executed_payload["decision"]
    assert executed_payload["execution"]["fake_transport"] is True
    audit_tail = run(["audit-tail", "--limit", "20"])
    audit_payload = json.loads(audit_tail.stdout)
    audit_text = json.dumps(audit_payload)
    assert device.ip_address in audit_text
    assert device.id not in audit_text
    state_text = "\n".join(path.read_text(encoding="utf-8") for path in state_dir.rglob("*") if path.is_file())
    assert "VaultSecret" not in state_text
    assert "SHOULD_NOT_LEAK" not in state_text
    dry_runs = json.loads((state_dir / "dry_runs.json").read_text(encoding="utf-8"))["dry_runs"]
    evaluations = json.loads((state_dir / "evaluations.json").read_text(encoding="utf-8"))["evaluations"]
    validations = json.loads((state_dir / "lab_validations.json").read_text(encoding="utf-8"))["lab_validations"]
    locks = json.loads((state_dir / "locks.json").read_text(encoding="utf-8"))["locks"]
    executions = [json.loads(path.read_text(encoding="utf-8")) for path in (state_dir / "executions").glob("*.json")]
    assert dry_runs[0]["device_ip"] == device.ip_address
    assert evaluations[0]["device_ip"] == device.ip_address
    assert validations[0]["device_ip"] == device.ip_address
    assert locks[0]["device_ip"] == device.ip_address
    assert executions[0]["device_ip"] == device.ip_address


def test_excel_lab_cli_import_does_not_load_db_session() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import scripts.excel_lab; print('app.db.session' in sys.modules)",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_excel_lab_cli_doctor_and_list_do_not_import_enterprise_runtime(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(tmp_path / "inventory.xlsx")
    state_dir = tmp_path / ".switchfleet_lab"
    code = """
import importlib.abc
import sys

blocked = ("app.db", "sqlalchemy", "alembic", "fastapi")


class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(blocked):
            raise ImportError(f"blocked enterprise import: {fullname}")
        return None


sys.meta_path.insert(0, Blocker())
import scripts.excel_lab as cli

cli.main(["--state-dir", sys.argv[2], sys.argv[1], "doctor"])
cli.main(["--state-dir", sys.argv[2], sys.argv[1], "list"])
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(inventory), str(state_dir)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert '"database_required": false' in result.stdout
    assert '"cisco_ios"' in result.stdout


def test_excel_lab_cli_safe_workflow_commands_do_not_import_enterprise_runtime(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(tmp_path / "inventory.xlsx")
    state_dir = tmp_path / ".switchfleet_lab"
    code = """
import importlib.abc
import os
import sys

blocked = ("app.db", "sqlalchemy", "alembic", "fastapi")


class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(blocked):
            raise ImportError(f"blocked enterprise import: {fullname}")
        return None


sys.meta_path.insert(0, Blocker())
os.environ["NCP_SECRET_KEY"] = "excel-lab-secret-key"
os.environ["SWITCHFLEET_TEST_PASSWORD"] = "VaultSecret"

import scripts.excel_lab as cli

cli.main(["--state-dir", sys.argv[2], sys.argv[1], "add-credential", "--name", "lab-admin", "--username", "admin", "--password-env", "SWITCHFLEET_TEST_PASSWORD"])
cli.main(["--state-dir", sys.argv[2], sys.argv[1], "dry-run", "--device", "192.0.2.67", "--operation", "vlan_create", "--vlan-id", "123", "--name", "TEST"])
cli.main(["--state-dir", sys.argv[2], sys.argv[1], "evaluate-apply", "--device", "192.0.2.67", "--credential", "lab-admin", "--operation", "vlan_create", "--vlan-id", "123", "--name", "TEST", "--simulation-hash", "missing"])
try:
    cli.main(["--state-dir", sys.argv[2], sys.argv[1], "backup", "--device", "192.0.2.67", "--credential", "lab-admin"])
except SystemExit as exc:
    assert "NCP_LAB_DEVICE_ALLOWLIST" in str(exc)
else:
    raise AssertionError("backup unexpectedly succeeded without allowlist")
cli.main(["--state-dir", sys.argv[2], sys.argv[1], "execute-apply", "--device", "192.0.2.67", "--credential", "lab-admin", "--operation", "vlan_create", "--vlan-id", "123", "--name", "TEST", "--simulation-hash", "missing"])
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(inventory), str(state_dir)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert '"credential"' in result.stdout
    assert '"command_hash"' in result.stdout
    assert '"allowed": false' in result.stdout


def test_switchfleet_lab_state_is_gitignored() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["git", "check-ignore", ".switchfleet_lab/credentials.json"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_excel_lab_docs_cover_cross_platform_local_install_and_no_db() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    scripts_readme = (repo_root / "scripts" / "README.md").read_text(encoding="utf-8")

    assert "Windows PowerShell" in readme
    assert "Linux/macOS shell" in readme
    assert "macOS uses the same Excel-first Python package path as Linux" in readme
    assert "workflow and local release bundles do not require Docker, PostgreSQL, Redis, Alembic, FastAPI startup, or a database" in readme
    assert "Windows, Linux, and macOS" in scripts_readme


def test_runnable_lab_docs_keep_required_workflow_order() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    docs = (repo_root / "docs" / "runnable-lab-prototype.md").read_text(encoding="utf-8")

    assert docs.index("switchfleet inventory.xlsx doctor") < docs.index("switchfleet inventory.xlsx summary")
    assert docs.index("switchfleet inventory.xlsx summary") < docs.index("switchfleet inventory.xlsx list")
    assert docs.index("switchfleet inventory.xlsx list") < docs.index("switchfleet inventory.xlsx check-runtime")
    assert docs.index("switchfleet inventory.xlsx add-credential") < docs.index("switchfleet inventory.xlsx backup")
    assert docs.index("switchfleet inventory.xlsx backup") < docs.index("switchfleet inventory.xlsx dry-run")
    assert docs.index("switchfleet inventory.xlsx dry-run") < docs.index("switchfleet inventory.xlsx evaluate-apply")
    assert docs.index("switchfleet inventory.xlsx evaluate-apply") < docs.index("switchfleet inventory.xlsx certify")
    assert "evaluations.json" in docs
    assert "matching stored evaluation" in docs
    assert docs.index("switchfleet inventory.xlsx certify") < docs.index("switchfleet inventory.xlsx execute-apply")


def test_local_working_version_checklist_is_linked_and_keeps_workflow_order() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    checklist = (repo_root / "docs" / "local-working-version-checklist.md").read_text(encoding="utf-8")

    assert "docs/local-working-version-checklist.md" in readme
    assert "Use IP address as the operator-facing device selector" in readme
    assert "Internal generated IDs are implementation details" in readme
    assert "--human" in readme
    assert ".switchfleet_lab/reports/" in readme
    assert "execute-apply --device 192.0.2.67 --profile examples/lab/vlan-profile.example.json" in readme
    assert "does not require PostgreSQL, Alembic, FastAPI startup, Redis, Docker, or database imports" in checklist
    assert "Use IP address as the operator-facing device selector" in checklist
    assert "Internal generated IDs are implementation details" in checklist
    assert "--human" in checklist
    assert ".switchfleet_lab/reports/" in checklist
    assert "execute-apply --device 192.0.2.67 --profile examples/lab/vlan-profile.example.json" in checklist
    assert checklist.index("switchfleet inventory.xlsx doctor") < checklist.index("switchfleet inventory.xlsx summary")
    assert checklist.index("switchfleet inventory.xlsx summary") < checklist.index("switchfleet inventory.xlsx list")
    assert checklist.index("switchfleet inventory.xlsx add-credential") < checklist.index("switchfleet inventory.xlsx backup")
    assert checklist.index("switchfleet inventory.xlsx backup") < checklist.index("switchfleet inventory.xlsx dry-run")
    assert checklist.index("switchfleet inventory.xlsx dry-run") < checklist.index("switchfleet inventory.xlsx evaluate-apply")
    assert checklist.index("switchfleet inventory.xlsx evaluate-apply") < checklist.index("switchfleet inventory.xlsx certify")
    assert checklist.index("switchfleet inventory.xlsx certify") < checklist.index("switchfleet inventory.xlsx execute-apply")


def test_lab_validation_docs_do_not_direct_users_to_legacy_real_apply() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    docs = (repo_root / "docs" / "lab-validation.md").read_text(encoding="utf-8")

    assert "switchfleet inventory.xlsx doctor" in docs
    assert "switchfleet inventory.xlsx backup" in docs
    assert "switchfleet inventory.xlsx evaluate-apply" in docs
    assert "switchfleet inventory.xlsx execute-apply" in docs
    assert "netops apply" not in docs
    assert "NCP_PRODUCTION_REAL_APPLY_ENABLED = \"false\"" in docs
