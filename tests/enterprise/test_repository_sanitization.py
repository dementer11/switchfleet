from __future__ import annotations

import re
import subprocess
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PRIVATE_IPV4_PATTERN = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})\b"
)
SANITIZED_PATH_PREFIXES = (
    "README.md",
    "docs/",
    "examples/",
    "scripts/README.md",
    "tests/",
)
FORBIDDEN_TRACKED_PARTS = (
    ".switchfleet_lab",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "dist",
    "build",
    "wheelhouse",
    "backups",
    "dry_runs",
    "executions",
    "reports",
)
FORBIDDEN_TRACKED_SUFFIXES = (
    ".egg-info",
    ".log",
    ".bak",
    ".backup",
    ".tmp",
    ".local",
    "credentials.json",
)


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def test_no_private_inventory_ips_in_committed_user_facing_files() -> None:
    offenders: list[str] = []
    for tracked_path in _tracked_files():
        if not tracked_path.startswith(SANITIZED_PATH_PREFIXES):
            continue
        path = REPO_ROOT / tracked_path
        if path.suffix.lower() in {".xlsx", ".png", ".jpg", ".jpeg", ".gif", ".ico"}:
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        if PRIVATE_IPV4_PATTERN.search(content):
            offenders.append(tracked_path)

    assert offenders == []


def test_no_private_inventory_ips_in_committed_spreadsheets() -> None:
    offenders: list[str] = []
    for tracked_path in _tracked_files():
        if not tracked_path.startswith(("examples/", "tests/fixtures/")):
            continue
        if not tracked_path.endswith(".xlsx"):
            continue
        with zipfile.ZipFile(REPO_ROOT / tracked_path) as workbook:
            for member in workbook.namelist():
                if not member.endswith(".xml"):
                    continue
                content = workbook.read(member).decode("utf-8", errors="ignore")
                if PRIVATE_IPV4_PATTERN.search(content):
                    offenders.append(tracked_path)
                    break

    assert offenders == []


def test_no_local_lab_artifacts_are_tracked() -> None:
    offenders = []
    for tracked_path in _tracked_files():
        parts = set(Path(tracked_path).parts)
        suffixes = (Path(tracked_path).suffix, Path(tracked_path).name)
        if parts.intersection(FORBIDDEN_TRACKED_PARTS):
            offenders.append(tracked_path)
            continue
        if any(tracked_path.endswith(suffix) for suffix in FORBIDDEN_TRACKED_SUFFIXES):
            offenders.append(tracked_path)
            continue
        if any(suffix in FORBIDDEN_TRACKED_SUFFIXES for suffix in suffixes):
            offenders.append(tracked_path)

    assert offenders == []
