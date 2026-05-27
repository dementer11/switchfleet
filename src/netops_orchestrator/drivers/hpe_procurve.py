from __future__ import annotations

from ..models import AccessLevel, AclRule, PortChange, VlanChange
from .base import CliDriver, DriverCapabilities


class HpeProcurveDriver(CliDriver):
    name = "hpe_procurve"
    capabilities = DriverCapabilities(acl=False)

    def change_password(self, username: str, new_password: str, level: AccessLevel = AccessLevel.admin):
        role = "manager" if level in {AccessLevel.admin, AccessLevel.enable} else "operator"
        commands = [
            "configure terminal",
            f"password {role} user-name {username} plaintext {new_password}",
            "exit",
        ]
        return self.plan("password", commands)

    def configure_acl(self, acl_name: str, rules: list[AclRule]):
        warnings = ["ACL syntax on ProCurve/ArubaOS-Switch varies by software train; implement after lab capture."]
        return self.plan("acl", [], warnings, read_only=True)

    def configure_vlan(self, change: VlanChange):
        commands = ["configure terminal", f"vlan {change.vlan_id}"]
        if change.name:
            commands.append(f"name {change.name}")
        if change.ports:
            ports = ",".join(change.ports)
            commands.append(f"{'untagged' if change.mode == 'access' else 'tagged'} {ports}")
        commands.extend(["exit", "exit"])
        return self.plan("vlan", commands)

    def configure_port(self, change: PortChange):
        commands = ["configure terminal", f"interface {change.interface}"]
        if change.description is not None:
            commands.append(f"name {change.description}")
        if change.enabled is not None:
            commands.append("enable" if change.enabled else "disable")
        commands.extend(["exit", "exit"])
        warnings = []
        if change.access_vlan is not None or change.trunk_vlans:
            warnings.append("Use plan-vlan for ProCurve VLAN membership; port VLAN syntax differs from IOS.")
        return self.plan("port", commands, warnings)

    def backup_config(self):
        return self.plan("backup", ["no page", "show running-config"], read_only=True)

    def save(self) -> tuple[str, ...]:
        return ("write memory",)
