from __future__ import annotations

from app.drivers.cisco_ios import CiscoIOSDriver
from app.drivers.base import DeviceCapabilities


class EltexMESDriver(CiscoIOSDriver):
    name = "EltexMESDriver"
    netmiko_device_type = "eltex"
    prompt_patterns = (r"[\w.\-()]+[>#]\s*$", r"[>#]\s*$")
    read_only_setup_commands = ("terminal datadump",)
    legacy_ssh_profile = "eltex_mes"

    def capabilities(self) -> DeviceCapabilities:
        base = super().capabilities()
        return DeviceCapabilities(
            **{
                **base.__dict__,
                "supports_save_config": False,
                "command_syntax_family": "eltex_mes",
                "destructive_apply_confirmed": False,
            }
        )

    def running_config_command(self) -> str:
        return "show running-config"

    def save_commands(self) -> list[str]:
        return []
