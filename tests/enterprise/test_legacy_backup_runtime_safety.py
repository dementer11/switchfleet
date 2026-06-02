from __future__ import annotations

import sys
from pathlib import Path

import pytest

from netops_orchestrator import cli
from netops_orchestrator.models import CommandPhase, CommandStep
from netops_orchestrator.transports.base import CommandResult


def _inventory(tmp_path: Path, vendor: str, model: str) -> Path:
    path = tmp_path / "inventory.csv"
    path.write_text(
        "label,ip address,vendor,model\n"
        f"sw1,10.0.0.1,{vendor},{model}\n",
        encoding="utf-8",
    )
    return path


class FakeReadOnlyTransport:
    def __init__(self) -> None:
        self.connected = False
        self.steps: list[CommandStep] = []

    def connect(self) -> None:
        self.connected = True

    def run_steps(self, steps: tuple[CommandStep, ...], stop_on_error: bool = True) -> list[CommandResult]:
        self.steps.extend(steps)
        assert all(step.read_only for step in steps)
        assert all(step.phase not in {CommandPhase.config, CommandPhase.save} for step in steps)
        return [
            CommandResult(
                command=step.command,
                output=f"{step.command}\n!",
                failed=False,
                phase=step.phase.value,
                redacted_command=step.command,
            )
            for step in steps
        ]

    def close(self) -> None:
        self.connected = False


def test_legacy_backup_uses_read_only_fake_transport_without_config_commands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    inventory = _inventory(tmp_path, "Cisco", "Catalyst 2960")
    output_dir = tmp_path / "backups"
    fake_transport = FakeReadOnlyTransport()

    monkeypatch.setattr(cli, "transport_for_plan", lambda *args, **kwargs: fake_transport)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "netops",
            "backup",
            str(inventory),
            "--login",
            "netops",
            "--password",
            "secret",
            "--output-dir",
            str(output_dir),
        ],
    )

    cli.main()

    assert fake_transport.steps
    assert list(output_dir.glob("*.cfg"))


def test_legacy_backup_unsupported_and_icmp_do_not_create_transport(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inventory = tmp_path / "inventory.csv"
    inventory.write_text(
        "label,ip address,vendor,model\n"
        "unknown,10.0.0.1,Huawei,Unknown Product\n"
        "icmp,10.0.0.2,ICMP-only,ICMP-only\n",
        encoding="utf-8",
    )

    def fail_transport(*args: object, **kwargs: object) -> object:
        raise AssertionError("Unsupported/ICMP backup must not create transport")

    monkeypatch.setattr(cli, "transport_for_plan", fail_transport)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "netops",
            "backup",
            str(inventory),
            "--login",
            "netops",
            "--password",
            "secret",
            "--limit",
            "2",
            "--continue-on-error",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    output = capsys.readouterr().out
    assert exc.value.code == 1
    assert "skipping 10.0.0.1: no backup commands" in output
    assert "skipping 10.0.0.2: no backup commands" in output
