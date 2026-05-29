from __future__ import annotations

from app.drivers.cisco_ios import CiscoIOSDriver
from app.drivers.base import DeviceCapabilities


class EltexMESDriver(CiscoIOSDriver):
    name = "EltexMESDriver"
    netmiko_device_type = "eltex"

    def capabilities(self) -> DeviceCapabilities:
        base = super().capabilities()
        return DeviceCapabilities(
            **{**base.__dict__, "command_syntax_family": "eltex_mes", "destructive_apply_confirmed": False}
        )

