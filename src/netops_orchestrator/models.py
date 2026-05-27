from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AccessLevel(str, Enum):
    readonly = "readonly"
    operator = "operator"
    admin = "admin"
    enable = "enable"


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
    warnings: tuple[str, ...] = ()
    read_only: bool = False

    @property
    def all_commands(self) -> tuple[str, ...]:
        return self.commands + self.save_commands


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
