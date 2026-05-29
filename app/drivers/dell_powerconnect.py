from __future__ import annotations

from app.drivers.cisco_ios import CiscoIOSDriver


class DellPowerConnectDriver(CiscoIOSDriver):
    name = "DellPowerConnectDriver"
    netmiko_device_type = "dell_powerconnect"

    def save_commands(self) -> list[str]:
        return ["copy running-config startup-config"]

