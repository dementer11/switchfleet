from __future__ import annotations

from dataclasses import dataclass

from ..models import AccessLevel, AclRule, CommandPlan, Device, PortChange, VlanChange


@dataclass(frozen=True)
class DriverCapabilities:
    password: bool = True
    acl: bool = True
    vlan: bool = True
    port: bool = True
    backup: bool = True
    save: bool = True


class CliDriver:
    name = "base"
    capabilities = DriverCapabilities()

    def __init__(self, device: Device):
        self.device = device

    def change_password(
        self,
        username: str,
        new_password: str,
        level: AccessLevel = AccessLevel.admin,
    ) -> CommandPlan:
        raise NotImplementedError

    def configure_acl(self, acl_name: str, rules: list[AclRule]) -> CommandPlan:
        raise NotImplementedError

    def configure_vlan(self, change: VlanChange) -> CommandPlan:
        raise NotImplementedError

    def configure_port(self, change: PortChange) -> CommandPlan:
        raise NotImplementedError

    def backup_config(self) -> CommandPlan:
        raise NotImplementedError

    def save(self) -> tuple[str, ...]:
        return ()

    def plan(
        self,
        operation: str,
        commands: list[str],
        warnings: list[str] | None = None,
        read_only: bool = False,
    ) -> CommandPlan:
        return CommandPlan(
            device=self.device,
            driver=self.name,
            operation=operation,
            commands=tuple(commands),
            save_commands=() if read_only else self.save(),
            warnings=tuple(warnings or ()),
            read_only=read_only,
        )


def privilege_level(level: AccessLevel) -> int:
    return {
        AccessLevel.readonly: 1,
        AccessLevel.operator: 5,
        AccessLevel.admin: 15,
        AccessLevel.enable: 15,
    }[level]


def hpe_privilege_level(level: AccessLevel) -> int:
    return {
        AccessLevel.readonly: 1,
        AccessLevel.operator: 2,
        AccessLevel.admin: 3,
        AccessLevel.enable: 3,
    }[level]
