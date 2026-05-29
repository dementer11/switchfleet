from app.drivers.base import VlanIntent
from app.drivers.huawei_vrp import HuaweiVRPDriver


def test_huawei_vlan_present_commands() -> None:
    result = HuaweiVRPDriver("10.0.0.1").plan_vlan_intent(VlanIntent(vlan_id=100, name="USERS", state="present"))

    assert result.commands == ["system-view", "vlan 100", "description USERS", "quit"]


def test_huawei_password_is_masked_in_dry_run() -> None:
    driver = HuaweiVRPDriver("10.0.0.1")
    driver.change_local_user_password("admin", "VerySecret")

    assert "VerySecret" not in "\n".join(driver.dry_run())

