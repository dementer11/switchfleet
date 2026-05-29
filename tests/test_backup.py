import tempfile
import unittest
import json
from pathlib import Path

from netops_orchestrator.audit import JsonlAuditLog
from netops_orchestrator.models import CommandPhase, CommandPlan, CommandStep, Device
from netops_orchestrator.orchestrator import apply_plan, backup_config
from netops_orchestrator.transports.base import CommandResult


class FakeTransport:
    def __init__(self):
        self.connected = False
        self.closed = False
        self.commands = []

    def connect(self):
        self.connected = True

    def run(self, command: str):
        self.commands.append(command)
        return CommandResult(command=command, output=f"{command}\nCONFIG-LINE\n<sw>")

    def close(self):
        self.closed = True


class FailingTransport(FakeTransport):
    def run(self, command: str):
        self.commands.append(command)
        return CommandResult(command=command, output="% Invalid input", failed=True, error="CLI rejected command")


class ConnectFailTransport(FakeTransport):
    def connect(self):
        raise RuntimeError("connection refused")


class StepAwareFakeTransport(FakeTransport):
    def run_steps(self, steps, stop_on_error=True):
        results = []
        for step in steps:
            self.commands.append(step.command)
            results.append(
                CommandResult(
                    command=step.command,
                    output="ok",
                    phase=step.phase.value,
                    redacted_command="<redacted>" if step.secret else step.command,
                )
            )
        return results


class BackupPipelineTests(unittest.TestCase):
    def test_backup_writes_captured_output_to_cfg_file(self):
        device = Device(label="sw-core", ip_address="10.0.0.10", vendor="Huawei", model="S5735")
        plan = CommandPlan(
            device=device,
            driver="huawei_vrp",
            operation="backup",
            commands=("screen-length 0 temporary", "display current-configuration"),
            read_only=True,
        )
        transport = FakeTransport()

        with tempfile.TemporaryDirectory() as tmp:
            path = backup_config(plan, transport, Path(tmp))
            content = path.read_text(encoding="utf-8")

        self.assertTrue(transport.connected)
        self.assertTrue(transport.closed)
        self.assertEqual(transport.commands, ["screen-length 0 temporary", "display current-configuration"])
        self.assertIn("# ip: 10.0.0.10", content)
        self.assertIn("### command: display current-configuration", content)
        self.assertIn("CONFIG-LINE", content)
        self.assertTrue(path.name.endswith(".cfg"))

    def test_empty_plan_does_not_connect(self):
        device = Device(label="unknown", ip_address="10.0.0.20", vendor="Unknown", model="ICMP")
        plan = CommandPlan(device=device, driver="unsupported_cli", operation="backup", commands=(), read_only=True)
        transport = FakeTransport()

        results = apply_plan(plan, transport)

        self.assertFalse(transport.connected)
        self.assertEqual(results, [])

    def test_backup_fail_on_error_writes_output_then_raises(self):
        device = Device(label="sw-core", ip_address="10.0.0.10", vendor="Huawei", model="S5735")
        plan = CommandPlan(
            device=device,
            driver="huawei_vrp",
            operation="backup",
            commands=("display current-configuration",),
            read_only=True,
        )
        transport = FailingTransport()

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "Backup command failed"):
                backup_config(plan, transport, Path(tmp), fail_on_error=True)
            backups = list(Path(tmp).glob("*.cfg"))
            self.assertEqual(len(backups), 1)
            content = backups[0].read_text(encoding="utf-8")

        self.assertIn("# failed: true", content)
        self.assertIn("# error: CLI rejected command", content)

    def test_audit_redacts_secret_commands(self):
        device = Device(label="sw-core", ip_address="10.0.0.10", vendor="Cisco", model="Catalyst")
        plan = CommandPlan(
            device=device,
            driver="cisco_ios",
            operation="password",
            commands=("username admin secret Secret123",),
            steps=(CommandStep("username admin secret Secret123", phase=CommandPhase.config, secret=True),),
        )
        transport = StepAwareFakeTransport()

        with tempfile.TemporaryDirectory() as tmp:
            audit = JsonlAuditLog(Path(tmp) / "audit.jsonl")
            apply_plan(plan, transport, audit=audit)
            records = [json.loads(line) for line in audit.path.read_text(encoding="utf-8").splitlines()]

        command_records = [record for record in records if record["event"] == "command_result"]
        self.assertEqual(command_records[0]["command"], "<redacted>")
        self.assertNotIn("Secret123", json.dumps(records))

    def test_audit_records_plan_error_on_connect_failure(self):
        device = Device(label="sw-core", ip_address="10.0.0.10", vendor="Cisco", model="Catalyst")
        plan = CommandPlan(device=device, driver="cisco_ios", operation="backup", commands=("show run",), read_only=True)

        with tempfile.TemporaryDirectory() as tmp:
            audit = JsonlAuditLog(Path(tmp) / "audit.jsonl")
            with self.assertRaisesRegex(RuntimeError, "connection refused"):
                apply_plan(plan, ConnectFailTransport(), audit=audit)
            records = [json.loads(line) for line in audit.path.read_text(encoding="utf-8").splitlines()]

        error_records = [record for record in records if record["event"] == "plan_error"]
        self.assertEqual(error_records[0]["error_type"], "RuntimeError")


if __name__ == "__main__":
    unittest.main()
