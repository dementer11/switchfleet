from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _clean_env_without_pythonpath() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    return env


def test_lab_prototype_script_help_runs_without_pythonpath() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/lab_prototype.py", "--help"],
        cwd=_repo_root(),
        env=_clean_env_without_pythonpath(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Runnable lab prototype" in result.stdout
    assert "bootstrap-admin" in result.stdout


def test_lab_prototype_execute_apply_help_runs_without_pythonpath() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/lab_prototype.py", "execute-apply", "--help"],
        cwd=_repo_root(),
        env=_clean_env_without_pythonpath(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--real-lab" in result.stdout
    assert "--simulation-hash" in result.stdout
