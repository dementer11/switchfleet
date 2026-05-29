import unittest

from netops_orchestrator.drivers.registry import driver_for
from netops_orchestrator.models import AccessLevel, AclRule, Device, PortChange, VlanChange


def device(vendor: str, model: str) -> Device:
    return Device(label="sw1", ip_address="10.0.0.1", vendor=vendor, model=model)


class DriverCommandTests(unittest.TestCase):
    def test_huawei_password_plan(self):
        plan = driver_for(device("Huawei", "S5735")).change_password("admin", "Secret123", AccessLevel.admin)

        self.assertEqual(plan.driver, "huawei_vrp")
        self.assertNotIn("system-view", plan.commands)
        self.assertIn("local-user admin password irreversible-cipher Secret123", plan.commands)
        self.assertEqual(plan.execution_steps[0].phase.value, "config")
        self.assertIn("<redacted>", plan.redacted_commands())
        self.assertEqual(plan.save_commands, ("save force",))
        self.assertEqual(plan.transport, "netmiko")
        self.assertEqual(plan.netmiko_device_type, "huawei_vrp")

    def test_comware_vlan_plan(self):
        plan = driver_for(device("Hewlett Packard", "HPE 1910-48")).configure_vlan(
            VlanChange(vlan_id=220, name="USERS", ports=("GigabitEthernet1/0/1",))
        )

        self.assertEqual(plan.driver, "comware_smb")
        self.assertIn("vlan 220", plan.commands)
        self.assertIn("port access vlan 220", plan.commands)
        self.assertEqual(plan.save_commands, ("save force",))
        self.assertIn("display vlan 220", plan.verify_commands)
        self.assertEqual(plan.execution_steps[-1].phase.value, "verify")

    def test_bulat_uses_first_party_driver(self):
        plan = driver_for(device("Bulat", "Bulat BS2500-48G4S-A")).change_password("ops", "Secret123")

        self.assertEqual(plan.driver, "bulat_bs")
        self.assertIn("username ops privilege 15 password 0 Secret123", plan.commands)
        self.assertEqual(plan.save_commands, ("write memory",))
        self.assertEqual(plan.transport, "paramiko")
        self.assertIsNone(plan.netmiko_device_type)
        self.assertTrue(plan.warnings)

    def test_save_steps_have_confirmation_responses(self):
        plan = driver_for(device("Eltex", "MES2448B")).change_password("ops", "Secret123")
        save_steps = [step for step in plan.execution_steps if step.phase.value == "save"]

        self.assertEqual(save_steps[0].command, "copy running-config startup-config")
        self.assertGreaterEqual(len(save_steps[0].responses), 2)

    def test_eltex_acl_plan(self):
        plan = driver_for(device("Eltex", "MES2448B")).configure_acl(
            "MGMT_ONLY",
            [AclRule(sequence=10, action="permit", protocol="tcp", source="10.0.0.0 0.0.0.255", destination="any")],
        )

        self.assertEqual(plan.driver, "eltex_mes")
        self.assertIn("ip access-list extended MGMT_ONLY", plan.commands)
        self.assertIn("10 permit tcp 10.0.0.0 0.0.0.255 any", plan.commands)
        self.assertEqual(plan.save_commands, ("copy running-config startup-config",))

    def test_qtech_port_plan(self):
        plan = driver_for(device("QTECH", "QSW-4610-52T-AC")).configure_port(
            PortChange(interface="ethernet 1/0/10", description="AP-10", enabled=True, access_vlan=30)
        )

        self.assertEqual(plan.driver, "qtech_qsw")
        self.assertIn("description AP-10", plan.commands)
        self.assertIn("switchport access vlan 30", plan.commands)
        self.assertIn("no shutdown", plan.commands)
        self.assertIn("show running-config interface ethernet 1/0/10", plan.verify_commands)

    def test_backup_commands_are_read_only(self):
        cases = [
            (device("Huawei", "S5735"), "display current-configuration"),
            (device("Eltex", "MES2324B"), "show running-config"),
            (device("QTECH", "QSW-4610-52T-AC"), "show running-config"),
            (device("Hewlett Packard", "HPE 2510-24 Switch"), "show running-config"),
        ]
        for dev, expected in cases:
            with self.subTest(dev=dev.model):
                plan = driver_for(dev).backup_config()
                self.assertEqual(plan.operation, "backup")
                self.assertTrue(plan.read_only)
                self.assertFalse(plan.save_commands)
                self.assertIn(expected, plan.commands)

    def test_unknown_device_is_not_mapped_to_cisco(self):
        plan = driver_for(device("Unknown", "ICMP")).backup_config()

        self.assertEqual(plan.driver, "unsupported_cli")
        self.assertFalse(plan.commands)
        self.assertTrue(plan.warnings)

    def test_unrecognized_device_is_unsupported(self):
        plan = driver_for(device("MysteryVendor", "SwitchOS 1.0")).backup_config()

        self.assertEqual(plan.driver, "unsupported_cli")
        self.assertFalse(plan.commands)


if __name__ == "__main__":
    unittest.main()
