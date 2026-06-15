import unittest

from netops_orchestrator.drivers.registry import driver_for
from netops_orchestrator.models import CommandPhase, CommandStep, Device
from netops_orchestrator.transports.factory import selected_transport_label, transport_for_plan
from netops_orchestrator.transports.errors import output_has_cli_error
from netops_orchestrator.transports.netmiko_ssh import NetmikoCliTransport
from netops_orchestrator.transports.ssh_paramiko import ParamikoCliTransport, SshCredentials


def device(vendor: str, model: str) -> Device:
    return Device(label="sw1", ip_address="192.0.2.1", vendor=vendor, model=model)


class TransportFactoryTests(unittest.TestCase):
    def test_auto_uses_netmiko_for_supported_platform(self):
        plan = driver_for(device("Cisco", "Catalyst 2960")).backup_config()
        transport = transport_for_plan(plan, SshCredentials(username="u", password="p"))

        self.assertEqual(plan.netmiko_device_type, "cisco_ios")
        self.assertEqual(selected_transport_label(plan), "netmiko:cisco_ios")
        self.assertIsInstance(transport, NetmikoCliTransport)
        self.assertEqual(transport.device_type, "cisco_ios")

    def test_auto_keeps_first_party_paramiko_for_bulat(self):
        plan = driver_for(device("Bulat", "Bulat BS2500-48G4S-A")).backup_config()
        transport = transport_for_plan(plan, SshCredentials(username="u", password="p"))

        self.assertIsNone(plan.netmiko_device_type)
        self.assertEqual(selected_transport_label(plan), "paramiko")
        self.assertIsInstance(transport, ParamikoCliTransport)

    def test_forced_netmiko_requires_mapping(self):
        plan = driver_for(device("Bulat", "Bulat BS2500-48G4S-A")).backup_config()

        with self.assertRaisesRegex(ValueError, "no Netmiko device_type"):
            transport_for_plan(plan, SshCredentials(username="u", password="p"), preference="netmiko")

    def test_forced_paramiko_overrides_netmiko_mapping(self):
        plan = driver_for(device("Huawei", "S5735")).backup_config()
        transport = transport_for_plan(plan, SshCredentials(username="u", password="p"), preference="paramiko")

        self.assertEqual(plan.netmiko_device_type, "huawei_vrp")
        self.assertEqual(selected_transport_label(plan, "paramiko"), "paramiko")
        self.assertIsInstance(transport, ParamikoCliTransport)

    def test_netmiko_groups_contiguous_config_steps(self):
        transport = NetmikoCliTransport("192.0.2.1", SshCredentials(username="u", password="p"), "cisco_ios")
        fake_connection = FakeNetmikoConnection()
        transport._connection = fake_connection

        results = transport.run_steps(
            (
                CommandStep("interface Gi1/0/1", phase=CommandPhase.config),
                CommandStep("description AP", phase=CommandPhase.config),
                CommandStep("write memory", phase=CommandPhase.save),
                CommandStep("show running-config interface Gi1/0/1", phase=CommandPhase.verify),
            )
        )

        self.assertEqual(fake_connection.config_sets, [["interface Gi1/0/1", "description AP"]])
        self.assertEqual(fake_connection.timing_commands, ["write memory", "show running-config interface Gi1/0/1"])
        self.assertEqual([result.phase for result in results], ["config", "save", "verify"])

    def test_common_cli_error_patterns_cover_vendor_outputs(self):
        self.assertTrue(output_has_cli_error("Error: Wrong parameter found at '^' position."))
        self.assertTrue(output_has_cli_error("% Incomplete command."))
        self.assertTrue(output_has_cli_error("Unknown command"))
        self.assertFalse(output_has_cli_error("description Last Error: power event"))


class FakeNetmikoConnection:
    def __init__(self):
        self.config_sets = []
        self.timing_commands = []

    def send_config_set(self, commands, **kwargs):
        self.config_sets.append(list(commands))
        return "\n".join(commands) + "\n(config)#"

    def send_command_timing(self, command, **kwargs):
        self.timing_commands.append(command)
        return command + "\n#"


if __name__ == "__main__":
    unittest.main()
