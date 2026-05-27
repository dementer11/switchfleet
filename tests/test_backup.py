import tempfile
import unittest
from pathlib import Path

from netops_orchestrator.models import CommandPlan, Device
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


if __name__ == "__main__":
    unittest.main()
