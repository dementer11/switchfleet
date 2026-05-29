from __future__ import annotations

from ..models import AccessLevel, AclRule, PortChange, VlanChange
from .base import CliDriver, DriverCapabilities


class HpeProcurveDriver(CliDriver):
    name = "hpe_procurve"
    netmiko_device_type = "hp_procurve"
    capabilities = DriverCapabilities(acl=False)

    def change_password(self, username: str, new_password: str, level: AccessLevel = AccessLevel.admin):
        role = "manager" if level in {AccessLevel.admin, AccessLevel.enable} else "operator"
        commands = [
            f"password {role} user-name {username} plaintext {new_password}",
        ]
        return self.config_plan("password", commands, secret_commands=set(commands))

    def configure_acl(self, acl_name: str, rules: list[AclRule]):
        warnings = ["ACL syntax on ProCurve/ArubaOS-Switch varies by software train; implement after lab capture."]
        return self.plan("acl", [], warnings, read_only=True)

    def configure_vlan(self, change: VlanChange):
        commands = [f"vlan {change.vlan_id}"]
        if change.name:
            commands.append(f"name {change.name}")
        if change.ports:
            ports = ",".join(change.ports)
            commands.append(f"{'untagged' if change.mode == 'access' else 'tagged'} {ports}")
        commands.append("exit")
        return self.config_plan("vlan", commands, verify_commands=[f"show vlans {change.vlan_id}"])

    def configure_port(self, change: PortChange):
        commands = [f"interface {change.interface}"]
        if change.description is not None:
            commands.append(f"name {change.description}")
        if change.enabled is not None:
            commands.append("enable" if change.enabled else "disable")
        commands.append("exit")
        warnings = []
        if change.access_vlan is not None or change.trunk_vlans:
            warnings.append("Use plan-vlan for ProCurve VLAN membership; port VLAN syntax differs from IOS.")
        return self.config_plan("port", commands, warnings, verify_commands=[f"show running-config interface {change.interface}"])

    def backup_config(self):
        return self.plan("backup", ["no page", "show running-config"], read_only=True)

    def save(self) -> tuple[str, ...]:
        return ("write memory",)
