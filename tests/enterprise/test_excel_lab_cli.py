from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from app.services.excel_inventory import load_excel_inventory
from app.services.file_lab_state import FileLabState
from tests.enterprise.excel_lab_helpers import write_inventory


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


def test_excel_lab_cli_summary_and_check_runtime_show_real_inventory_status(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inventory = write_inventory(
        tmp_path / "inventory.xlsx",
        [
            ["Active", "qtech-lab", "QSW-4610", "10.13.4.67", "QTECH", "Switch", "Lab", "NetOps"],
            ["Active", "continent", "Continent-500", "10.13.4.68", "SecurityCode", "Security Appliance", "Lab", "SecOps"],
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
        [sys.executable, "scripts/excel_lab.py", str(inventory), "check-runtime", "--device", "qtech-lab"],
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
    assert '"original_vendor": "QTECH"' in runtime.stdout
    assert '"normalized_vendor": "QTECH"' in runtime.stdout
    assert '"family": "qtech"' in runtime.stdout
    assert '"transport": "custom_cli"' in runtime.stdout
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
            "sw1-lab",
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
    assert "lab_validation" in json.loads(before_cert.stdout)["denied_gates"]
    run(["certify", "--device", device.ip_address, "--capability", "vlan_create", "--credential", "lab-admin"])
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
    assert json.loads(after_cert.stdout)["allowed"] is True
    executed = run(
        [
            "execute-apply",
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
    assert json.loads(executed.stdout)["execution"]["fake_transport"] is True
    state_text = "\n".join(path.read_text(encoding="utf-8") for path in state_dir.rglob("*") if path.is_file())
    assert "VaultSecret" not in state_text
    assert "SHOULD_NOT_LEAK" not in state_text


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
cli.main(["--state-dir", sys.argv[2], sys.argv[1], "dry-run", "--device", "sw1-lab", "--operation", "vlan_create", "--vlan-id", "123", "--name", "TEST"])
cli.main(["--state-dir", sys.argv[2], sys.argv[1], "evaluate-apply", "--device", "sw1-lab", "--credential", "lab-admin", "--operation", "vlan_create", "--vlan-id", "123", "--name", "TEST", "--simulation-hash", "missing"])
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
    assert docs.index("switchfleet inventory.xlsx certify") < docs.index("switchfleet inventory.xlsx execute-apply")


def test_lab_validation_docs_do_not_direct_users_to_legacy_real_apply() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    docs = (repo_root / "docs" / "lab-validation.md").read_text(encoding="utf-8")

    assert "switchfleet inventory.xlsx doctor" in docs
    assert "switchfleet inventory.xlsx backup" in docs
    assert "switchfleet inventory.xlsx evaluate-apply" in docs
    assert "switchfleet inventory.xlsx execute-apply" in docs
    assert "netops apply" not in docs
    assert "NCP_PRODUCTION_REAL_APPLY_ENABLED = \"false\"" in docs
