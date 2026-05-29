import tempfile
import unittest
from pathlib import Path

from netops_orchestrator.drivers.registry import driver_for
from netops_orchestrator.models import AccessLevel, Device
from netops_orchestrator.plan_io import read_plans, write_plans


class PlanIoTests(unittest.TestCase):
    def test_round_trip_preserves_steps_and_transport(self):
        device = Device(label="sw1", ip_address="10.0.0.1", vendor="Huawei", model="S5735")
        plan = driver_for(device).change_password("admin", "Secret123", AccessLevel.admin)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            write_plans(path, [plan], redact_secrets=False)
            restored = read_plans(path)[0]

        self.assertEqual(restored.driver, "huawei_vrp")
        self.assertEqual(restored.netmiko_device_type, "huawei_vrp")
        self.assertEqual(restored.execution_steps[0].phase.value, "config")
        self.assertTrue(any(step.secret for step in restored.execution_steps))

    def test_redacted_plan_file_does_not_include_secret(self):
        device = Device(label="sw1", ip_address="10.0.0.1", vendor="Cisco", model="Catalyst 2960")
        plan = driver_for(device).change_password("admin", "Secret123", AccessLevel.admin)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            write_plans(path, [plan], redact_secrets=True)
            content = path.read_text(encoding="utf-8")

        self.assertNotIn("Secret123", content)
        self.assertIn("<redacted>", content)


if __name__ == "__main__":
    unittest.main()
