from app.drivers.base import PortIntent, VlanIntent
from app.drivers.cisco_ios import CiscoIOSDriver


def test_cisco_vlan_present_commands() -> None:
    result = CiscoIOSDriver("10.0.0.2").plan_vlan_intent(VlanIntent(vlan_id=100, name="USERS", state="present"))

    assert result.commands == ["configure terminal", "vlan 100", "name USERS", "exit", "end"]


def test_cisco_trunk_commands() -> None:
    commands = CiscoIOSDriver("10.0.0.2").render_trunk_port(
        PortIntent(
            interface="GigabitEthernet1/0/1",
            mode="trunk",
            access_vlan=None,
            allowed_vlans=[10, 20, 21, 22],
            native_vlan=99,
            description="UPLINK",
            admin_state="up",
        )
    )

    assert "switchport trunk allowed vlan 10,20-22" in commands
    assert "switchport trunk native vlan 99" in commands

