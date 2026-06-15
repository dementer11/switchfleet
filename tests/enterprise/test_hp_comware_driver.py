from app.drivers.base import VlanIntent
from app.drivers.hp_comware import HPComwareDriver


def test_hp_comware_vlan_present_commands() -> None:
    result = HPComwareDriver("192.0.2.3").plan_vlan_intent(VlanIntent(vlan_id=100, name="USERS", state="present"))

    assert result.commands == ["system-view", "vlan 100", "name USERS", "quit", "quit"]

