from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

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
