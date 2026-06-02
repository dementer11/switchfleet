from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from netops_orchestrator import cli


def _inventory(tmp_path: Path, vendor: str = "Cisco", model: str = "Catalyst 2960") -> Path:
    path = tmp_path / "inventory.csv"
    path.write_text(
        "label,ip address,vendor,model\n"
        f"sw1,10.0.0.1,{vendor},{model}\n",
        encoding="utf-8",
    )
    return path


def test_legacy_cli_apply_is_blocked_before_transport_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    inventory = _inventory(tmp_path)

    def fail_transport(*args: object, **kwargs: object) -> object:
        raise AssertionError("transport_for_plan must not be called when apply is blocked")

    monkeypatch.setattr(cli, "transport_for_plan", fail_transport)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "netops",
            "apply",
            str(inventory),
            "--operation",
            "vlan",
            "--vlan-id",
            "120",
            "--login",
            "netops",
            "--password",
            "secret",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert "Legacy CLI real apply is disabled" in str(exc.value)
    assert "lab-only real apply stage" in str(exc.value)


def test_legacy_cli_apply_blocked_before_netmiko_or_paramiko_session_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    inventory = _inventory(tmp_path)

    def fail_session_open(*args: object, **kwargs: object) -> object:
        raise AssertionError("Real SSH session open must not be reached")

    fake_paramiko = types.SimpleNamespace(
        SSHClient=fail_session_open,
        AutoAddPolicy=lambda: object(),
    )
    fake_netmiko = types.SimpleNamespace(ConnectHandler=fail_session_open)

    monkeypatch.setitem(sys.modules, "paramiko", fake_paramiko)
    monkeypatch.setitem(sys.modules, "netmiko", fake_netmiko)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "netops",
            "apply",
            str(inventory),
            "--operation",
            "vlan",
            "--vlan-id",
            "120",
            "--login",
            "netops",
            "--password",
            "secret",
            "--pre-backup",
            "--post-backup",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert "Legacy CLI real apply is disabled" in str(exc.value)


def test_legacy_cli_apply_env_flag_still_does_not_enable_real_apply(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    inventory = _inventory(tmp_path)
    monkeypatch.setenv("NCP_LEGACY_CLI_REAL_APPLY", "true")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "netops",
            "apply",
            str(inventory),
            "--operation",
            "vlan",
            "--vlan-id",
            "120",
            "--login",
            "netops",
            "--password",
            "secret",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert "still blocks it" in str(exc.value)


def test_legacy_cli_apply_dry_run_still_renders_plan(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    inventory = _inventory(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "netops",
            "apply",
            str(inventory),
            "--operation",
            "vlan",
            "--vlan-id",
            "120",
            "--name",
            "CAMERAS",
            "--dry-run",
        ],
    )

    cli.main()

    output = capsys.readouterr().out
    assert "vlan 120" in output
    assert "CAMERAS" in output
    assert "via netmiko:cisco_ios" in output


def test_legacy_plan_commands_still_work(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    inventory = _inventory(tmp_path, vendor="Huawei", model="S5735")
    monkeypatch.setattr(
        sys,
        "argv",
        ["netops", "plan-backup", str(inventory)],
    )

    cli.main()

    output = capsys.readouterr().out
    assert "display current-configuration" in output
    assert "via netmiko:huawei_vrp" in output
