from __future__ import annotations

from ..models import AccessLevel, AclRule, PortChange, VlanChange
from .base import CliDriver, privilege_level


class EltexMesDriver(CliDriver):
    name = "eltex_mes"
    netmiko_device_type = "eltex"

    def change_password(self, username: str, new_password: str, level: AccessLevel = AccessLevel.admin):
        commands = [
            f"username {username} password {new_password} privilege {privilege_level(level)}",
        ]
        return self.config_plan("password", commands, secret_commands=set(commands))

    def configure_acl(self, acl_name: str, rules: list[AclRule]):
        commands = [f"ip access-list extended {acl_name}"]
        commands.extend(
            f"{rule.sequence} {rule.action} {rule.protocol} {rule.source} {rule.destination}"
            + (f" {rule.extra}" if rule.extra else "")
            for rule in rules
        )
        commands.append("exit")
        return self.config_plan("acl", commands, verify_commands=[f"show access-lists {acl_name}"])

    def configure_vlan(self, change: VlanChange):
        commands = ["vlan database", f"vlan {change.vlan_id}"]
        if change.name:
            commands.append(f"name {change.name}")
        commands.append("exit")
        for port in change.ports:
            commands.extend([f"interface {port}", f"switchport mode {change.mode}"])
            if change.mode == "access":
                commands.append(f"switchport access vlan {change.vlan_id}")
            else:
                commands.append(f"switchport trunk allowed vlan add {change.vlan_id}")
            commands.append("exit")
        return self.config_plan("vlan", commands, verify_commands=[f"show vlan id {change.vlan_id}"])

    def configure_port(self, change: PortChange):
        commands = [f"interface {change.interface}"]
        if change.description is not None:
            commands.append(f"description {change.description}")
        if change.access_vlan is not None:
            commands.extend(["switchport mode access", f"switchport access vlan {change.access_vlan}"])
        if change.trunk_vlans:
            vlans = ",".join(str(vlan) for vlan in change.trunk_vlans)
            commands.extend(["switchport mode trunk", f"switchport trunk allowed vlan add {vlans}"])
        if change.enabled is not None:
            commands.append("no shutdown" if change.enabled else "shutdown")
        commands.append("exit")
        return self.config_plan("port", commands, verify_commands=[f"show running-config interface {change.interface}"])

    def backup_config(self):
        return self.plan("backup", ["terminal datadump", "show running-config"], read_only=True)

    def save(self) -> tuple[str, ...]:
        return ("copy running-config startup-config",)
