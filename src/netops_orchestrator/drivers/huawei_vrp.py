from __future__ import annotations

from ..models import AccessLevel, AclRule, PortChange, VlanChange
from .base import CliDriver, privilege_level


class HuaweiVrpDriver(CliDriver):
    name = "huawei_vrp"
    netmiko_device_type = "huawei_vrp"

    def change_password(self, username: str, new_password: str, level: AccessLevel = AccessLevel.admin):
        commands = [
            "aaa",
            f"local-user {username} password irreversible-cipher {new_password}",
            f"local-user {username} privilege level {privilege_level(level)}",
            f"local-user {username} service-type ssh terminal",
            "quit",
        ]
        secrets = {command for command in commands if new_password in command}
        return self.config_plan("password", commands, secret_commands=secrets)

    def configure_acl(self, acl_name: str, rules: list[AclRule]):
        acl_id = _acl_number(acl_name)
        commands = [f"acl name {acl_name} {acl_id}"]
        commands.extend(
            f"rule {rule.sequence} {rule.action} {rule.protocol} source {rule.source} destination {rule.destination}"
            + (f" {rule.extra}" if rule.extra else "")
            for rule in rules
        )
        commands.append("quit")
        return self.config_plan("acl", commands, verify_commands=[f"display acl name {acl_name}"])

    def configure_vlan(self, change: VlanChange):
        commands = [f"vlan {change.vlan_id}"]
        if change.name:
            commands.append(f"description {change.name}")
        commands.append("quit")
        for port in change.ports:
            commands.extend([f"interface {port}", f"port link-type {change.mode}"])
            if change.mode == "access":
                commands.append(f"port default vlan {change.vlan_id}")
            else:
                commands.append(f"port trunk allow-pass vlan {change.vlan_id}")
            commands.append("quit")
        return self.config_plan("vlan", commands, verify_commands=[f"display vlan {change.vlan_id}"])

    def configure_port(self, change: PortChange):
        commands = [f"interface {change.interface}"]
        if change.description is not None:
            commands.append(f"description {change.description}")
        if change.access_vlan is not None:
            commands.extend(["port link-type access", f"port default vlan {change.access_vlan}"])
        if change.trunk_vlans:
            vlans = " ".join(str(vlan) for vlan in change.trunk_vlans)
            commands.extend(["port link-type trunk", f"port trunk allow-pass vlan {vlans}"])
        if change.enabled is not None:
            commands.append("undo shutdown" if change.enabled else "shutdown")
        commands.append("quit")
        return self.config_plan("port", commands, verify_commands=[f"display current-configuration interface {change.interface}"])

    def backup_config(self):
        return self.plan("backup", ["screen-length 0 temporary", "display current-configuration"], read_only=True)

    def save(self) -> tuple[str, ...]:
        return ("save force",)


def _acl_number(acl_name: str) -> int:
    return int(acl_name) if acl_name.isdigit() else 3000
