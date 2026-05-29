from __future__ import annotations

from dataclasses import dataclass

from ..models import (
    AccessLevel,
    AclRule,
    CommandPhase,
    CommandPlan,
    CommandStep,
    Device,
    PortChange,
    PromptResponse,
    VlanChange,
)


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
    netmiko_device_type: str | None = None

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

    def save_steps(self) -> tuple[CommandStep, ...]:
        return tuple(
            CommandStep(command, phase=CommandPhase.save, responses=self.save_responses(command))
            for command in self.save()
        )

    def save_responses(self, command: str) -> tuple[PromptResponse, ...]:
        enter = PromptResponse(r"Destination filename|\[confirm\]|confirm", "")
        yes = PromptResponse(r"\[Y/N\]|\(y/n\)|are you sure|continue\?|overwrite", "y")
        if command.startswith("copy running-config"):
            return (enter, yes)
        if command.startswith(("save", "write")):
            return (yes, enter)
        return ()

    def plan(
        self,
        operation: str,
        commands: list[str],
        warnings: list[str] | None = None,
        read_only: bool = False,
        phase: CommandPhase = CommandPhase.exec,
        secret_commands: set[str] | None = None,
        verify_commands: list[str] | None = None,
    ) -> CommandPlan:
        secrets = secret_commands or set()
        command_phase = CommandPhase.exec if read_only else phase
        command_steps = tuple(
            CommandStep(
                command,
                phase=command_phase,
                read_only=read_only,
                secret=command in secrets,
            )
            for command in commands
        )
        verify_steps = tuple(
            CommandStep(command, phase=CommandPhase.verify, read_only=True)
            for command in (verify_commands or [])
        )
        steps = command_steps + (() if read_only else self.save_steps()) + verify_steps
        return CommandPlan(
            device=self.device,
            driver=self.name,
            operation=operation,
            commands=tuple(commands),
            save_commands=() if read_only else self.save(),
            verify_commands=tuple(verify_commands or ()),
            warnings=tuple(warnings or ()),
            read_only=read_only,
            transport="netmiko" if self.netmiko_device_type else "paramiko",
            netmiko_device_type=self.netmiko_device_type,
            steps=steps,
        )

    def config_plan(
        self,
        operation: str,
        commands: list[str],
        warnings: list[str] | None = None,
        secret_commands: set[str] | None = None,
        verify_commands: list[str] | None = None,
    ) -> CommandPlan:
        return self.plan(
            operation,
            commands,
            warnings=warnings,
            phase=CommandPhase.config,
            secret_commands=secret_commands,
            verify_commands=verify_commands,
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
