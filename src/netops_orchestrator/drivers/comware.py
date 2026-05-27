from __future__ import annotations

from ..models import AccessLevel, AclRule, PortChange, VlanChange
from .base import CliDriver, hpe_privilege_level


ROLE_BY_LEVEL = {
    AccessLevel.readonly: "network-operator",
    AccessLevel.operator: "network-admin",
    AccessLevel.admin: "network-admin",
    AccessLevel.enable: "network-admin",
}


class ComwareSmbDriver(CliDriver):
    name = "comware_smb"

    def change_password(self, username: str, new_password: str, level: AccessLevel = AccessLevel.admin):
        commands = [
            "system-view",
            f"local-user {username}",
            f"password cipher {new_password}",
            "service-type ssh terminal",
            f"authorization-attribute level {hpe_privilege_level(level)}",
            "quit",
            "quit",
        ]
        warnings = ["HPE 1910/1920 may require hidden _cmdline-mode before system-view on some firmware."]
        return self.plan("password", commands, warnings)

    def configure_acl(self, acl_name: str, rules: list[AclRule]):
        acl_id = int(acl_name) if acl_name.isdigit() else 3000
        commands = ["system-view", f"acl advanced {acl_id}"]
        commands.extend(
            f"rule {rule.sequence} {rule.action} {rule.protocol} source {rule.source} destination {rule.destination}"
            + (f" {rule.extra}" if rule.extra else "")
            for rule in rules
        )
        commands.extend(["quit", "quit"])
        return self.plan("acl", commands)

    def configure_vlan(self, change: VlanChange):
        commands = ["system-view", f"vlan {change.vlan_id}"]
        if change.name:
            commands.append(f"name {change.name}")
        commands.append("quit")
        for port in change.ports:
            commands.extend([f"interface {port}", f"port link-type {change.mode}"])
            if change.mode == "access":
                commands.append(f"port access vlan {change.vlan_id}")
            else:
                commands.append(f"port trunk permit vlan {change.vlan_id}")
            commands.append("quit")
        commands.append("quit")
        return self.plan("vlan", commands)

    def configure_port(self, change: PortChange):
        commands = ["system-view", f"interface {change.interface}"]
        if change.description is not None:
            commands.append(f"description {change.description}")
        if change.access_vlan is not None:
            commands.extend(["port link-type access", f"port access vlan {change.access_vlan}"])
        if change.trunk_vlans:
            vlans = " ".join(str(vlan) for vlan in change.trunk_vlans)
            commands.extend(["port link-type trunk", f"port trunk permit vlan {vlans}"])
        if change.enabled is not None:
            commands.append("undo shutdown" if change.enabled else "shutdown")
        commands.extend(["quit", "quit"])
        return self.plan("port", commands)

    def backup_config(self):
        return self.plan("backup", ["screen-length disable", "display current-configuration"], read_only=True)

    def save(self) -> tuple[str, ...]:
        return ("save force",)


class ComwareLegacyDriver(ComwareSmbDriver):
    name = "comware_legacy"

    def change_password(self, username: str, new_password: str, level: AccessLevel = AccessLevel.admin):
        commands = [
            "system-view",
            f"local-user {username}",
            f"password cipher {new_password}",
            f"service-type ssh telnet terminal level {hpe_privilege_level(level)}",
            "quit",
            "quit",
        ]
        return self.plan("password", commands)


class Comware7Driver(ComwareSmbDriver):
    name = "comware7"

    def change_password(self, username: str, new_password: str, level: AccessLevel = AccessLevel.admin):
        commands = [
            "system-view",
            f"local-user {username} class manage",
            f"password irreversible-cipher {new_password}",
            "service-type ssh terminal",
            f"authorization-attribute user-role {ROLE_BY_LEVEL[level]}",
            "quit",
            "quit",
        ]
        return self.plan("password", commands)
