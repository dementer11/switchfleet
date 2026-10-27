from __future__ import annotations

from dataclasses import dataclass, field

from app.fleet.network import execute_device
from app.fleet.profiles import build_device_plan
from app.transports.base import CommandExecutionResult


@dataclass
class FakeTransport:
    responses: dict[str, CommandExecutionResult] = field(default_factory=dict)
    seen: list[str] = field(default_factory=list)
    closed: bool = False

    def open(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def run_command(self, command: str, timeout_seconds: int = 60) -> CommandExecutionResult:
        self.seen.append(command)
        return self.responses.get(command, CommandExecutionResult(command, "ok", True))

    def run_read_only_backup_command(self, command: str, timeout_seconds: int = 60, **kwargs) -> CommandExecutionResult:
        self.seen.append(command)
        return self.responses.get(command, CommandExecutionResult(command, "hostname edge\nend\n", True))


def plan(operation: str = "vlan_create", parameters: dict | None = None) -> dict:
    return build_device_plan({"id": "sw-1", "label": "edge", "ip_address": "192.0.2.10", "vendor": "Cisco", "model": "2960", "family": "cisco_ios"}, operation, parameters or {"vlan_id": 42, "name": "USERS"})


def creds(**extra) -> dict:
    return {"username": "operator-secret", "password": "login-secret", **extra}


def test_mutating_plan_takes_backup_before_any_write(monkeypatch) -> None:
    fake = FakeTransport()
    monkeypatch.setattr("app.fleet.network._create_transport", lambda *args: fake)
    result = execute_device(plan(), creds())
    assert result["status"] == "succeeded"
    assert result["changed"] is True
    assert fake.seen.index("show running-config") < fake.seen.index("configure terminal")
    assert result["verification"] == "commands_completed"
    assert result["verification"] != "verified"
    assert fake.closed


def test_backup_failure_blocks_every_write_and_keeps_partial_backup(monkeypatch) -> None:
    fake = FakeTransport(responses={"show running-config": CommandExecutionResult("show running-config", "hostname edge\n", False, "backup failed")})
    monkeypatch.setattr("app.fleet.network._create_transport", lambda *args: fake)
    result = execute_device(plan(), creds())
    assert result["status"] == "failed"
    assert result["changed"] is False
    assert "configure terminal" not in fake.seen
    assert result["backup_text"] == "hostname edge"


def test_vendor_error_in_successful_backup_response_blocks_writes(monkeypatch) -> None:
    fake = FakeTransport(responses={"show running-config": CommandExecutionResult("show running-config", "% Invalid input detected", True)})
    monkeypatch.setattr("app.fleet.network._create_transport", lambda *args: fake)
    result = execute_device(plan(), creds())
    assert result["status"] == "failed"
    assert result["changed"] is False
    assert "configure terminal" not in fake.seen


def test_empty_cleaned_backup_blocks_writes(monkeypatch) -> None:
    fake = FakeTransport(responses={"show running-config": CommandExecutionResult("show running-config", "show running-config\nedge#\n", True)})
    monkeypatch.setattr("app.fleet.network._create_transport", lambda *args: fake)
    result = execute_device(plan(), creds())
    assert result["status"] == "failed"
    assert result["changed"] is False
    assert "configure terminal" not in fake.seen


def test_vendor_error_stops_remaining_commands(monkeypatch) -> None:
    failing = "vlan 42"
    fake = FakeTransport(responses={failing: CommandExecutionResult(failing, "% Invalid input", True)})
    monkeypatch.setattr("app.fleet.network._create_transport", lambda *args: fake)
    result = execute_device(plan(), creds())
    assert result["status"] == "failed"
    assert "name USERS" not in fake.seen
    assert result["backup_text"] is not None
    assert result["changed"] is True


def test_password_is_injected_at_execution_then_redacted_everywhere(monkeypatch) -> None:
    secret = "super-secret-password"
    password_plan = plan("password_change", {"username": "operator", "level": 15})
    fake = FakeTransport()
    monkeypatch.setattr("app.fleet.network._create_transport", lambda *args: fake)
    result = execute_device(password_plan, creds(new_password=secret))
    assert result["status"] == "succeeded"
    assert any(secret in command for command in fake.seen)
    assert secret not in str(result)
    assert secret not in str(password_plan)


def test_unsupported_and_cancelled_plans_open_no_transport(monkeypatch) -> None:
    created: list[bool] = []
    monkeypatch.setattr("app.fleet.network._create_transport", lambda *args: created.append(True))
    unsupported = execute_device({**plan(), "status": "unsupported", "error": "unsupported"}, creds())
    cancelled = execute_device(plan(), creds(), cancelled=lambda: True)
    assert unsupported["status"] == "unsupported"
    assert cancelled["status"] == "cancelled"
    assert created == []


def test_readonly_backup_never_marks_changed(monkeypatch) -> None:
    fake = FakeTransport()
    monkeypatch.setattr("app.fleet.network._create_transport", lambda *args: fake)
    result = execute_device(plan("backup", {}), creds())
    assert result["status"] == "succeeded"
    assert result["changed"] is False
    assert result["backup_text"] is not None


def test_facts_collect_version_without_mislabeling_backup(monkeypatch) -> None:
    fake = FakeTransport(responses={"show version": CommandExecutionResult("show version", "Cisco IOS Software, version 1", True)})
    monkeypatch.setattr("app.fleet.network._create_transport", lambda *args: fake)
    facts_plan = plan("facts", {})
    result = execute_device(facts_plan, creds())
    assert result["status"] == "succeeded"
    assert fake.seen == ["show version"]
    assert result["backup_text"] is None
    assert result["changed"] is False


def test_readonly_backup_file_excludes_setup_transcript_and_prompt(monkeypatch) -> None:
    fake = FakeTransport(
        responses={
            "screen-length disable": CommandExecutionResult("screen-length disable", "pager disabled\n<sw1>\n", True),
            "display current-configuration": CommandExecutionResult("display current-configuration", "display current-configuration\nsysname edge\n<sw1>\n", True),
        }
    )
    monkeypatch.setattr("app.fleet.network._create_transport", lambda *args: fake)
    comware_plan = build_device_plan(
        {"id": "sw-c", "label": "comware", "ip_address": "192.0.2.11", "vendor": "HPE", "model": "1910", "family": "hpe_comware"},
        "backup",
        {},
    )
    result = execute_device(comware_plan, creds())
    assert result["status"] == "succeeded"
    assert result["backup_text"] == "sysname edge"
    assert "pager disabled" not in result["backup_text"]
    assert "<sw1>" not in result["backup_text"]
    assert "pager disabled" in result["output"]


def test_ssh_username_is_not_redacted_as_a_secret(monkeypatch) -> None:
    fake = FakeTransport(responses={"show version": CommandExecutionResult("show version", "show version\nadmin account active\nedge#", True)})
    monkeypatch.setattr("app.fleet.network._create_transport", lambda *args: fake)
    result = execute_device(plan("facts", {}), creds(username="admin"))
    assert result["status"] == "succeeded"
    assert "admin account active" in result["output"]
