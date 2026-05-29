from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AccessLevel(str, Enum):
    readonly = "readonly"
    operator = "operator"
    admin = "admin"
    enable = "enable"


class CommandPhase(str, Enum):
    exec = "exec"
    config = "config"
    save = "save"
    verify = "verify"


@dataclass(frozen=True)
class PromptResponse:
    pattern: str
    response: str
    hidden: bool = False


@dataclass(frozen=True)
class CommandStep:
    command: str
    phase: CommandPhase = CommandPhase.exec
    responses: tuple[PromptResponse, ...] = ()
    expected_prompt: str | None = None
    read_only: bool = False
    secret: bool = False
    error_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class Device:
    label: str
    ip_address: str
    vendor: str
    model: str
    category: str = ""
    location: str = ""
    contact: str = ""
    status: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CommandPlan:
    device: Device
    driver: str
    operation: str
    commands: tuple[str, ...]
    save_commands: tuple[str, ...] = ()
    verify_commands: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    read_only: bool = False
    transport: str = "paramiko"
    netmiko_device_type: str | None = None
    steps: tuple[CommandStep, ...] = ()

    @property
    def all_commands(self) -> tuple[str, ...]:
        return tuple(step.command for step in self.execution_steps)

    @property
    def execution_steps(self) -> tuple[CommandStep, ...]:
        if self.steps:
            return self.steps
        return (
            tuple(CommandStep(command, read_only=self.read_only) for command in self.commands)
            + tuple(CommandStep(command, phase=CommandPhase.save) for command in self.save_commands)
            + tuple(CommandStep(command, phase=CommandPhase.verify, read_only=True) for command in self.verify_commands)
        )

    def redacted_commands(self) -> tuple[str, ...]:
        return tuple("<redacted>" if step.secret else step.command for step in self.execution_steps)


@dataclass(frozen=True)
class AclRule:
    sequence: int
    action: str
    protocol: str = "ip"
    source: str = "any"
    destination: str = "any"
    extra: str = ""


@dataclass(frozen=True)
class VlanChange:
    vlan_id: int
    name: str | None = None
    ports: tuple[str, ...] = ()
    mode: str = "access"


@dataclass(frozen=True)
class PortChange:
    interface: str
    description: str | None = None
    enabled: bool | None = None
    access_vlan: int | None = None
    trunk_vlans: tuple[int, ...] = ()
