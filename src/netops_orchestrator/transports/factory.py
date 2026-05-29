from __future__ import annotations

from typing import Literal

from ..models import CommandPlan
from .base import CliTransport
from .netmiko_ssh import NetmikoCliTransport, NetmikoConnectionOptions
from .ssh_paramiko import ParamikoCliTransport, SshCredentials


TransportPreference = Literal["auto", "netmiko", "paramiko"]
TRANSPORT_CHOICES: tuple[TransportPreference, ...] = ("auto", "netmiko", "paramiko")


def transport_for_plan(
    plan: CommandPlan,
    credentials: SshCredentials,
    preference: TransportPreference = "auto",
    port: int = 22,
    timeout: float = 15.0,
    read_timeout: float = 120.0,
) -> CliTransport:
    if preference not in TRANSPORT_CHOICES:
        raise ValueError(f"Unsupported transport preference: {preference}")
    if preference == "netmiko" or (preference == "auto" and plan.netmiko_device_type):
        if not plan.netmiko_device_type:
            raise ValueError(f"Driver {plan.driver} has no Netmiko device_type mapping")
        return NetmikoCliTransport(
            plan.device.ip_address,
            credentials,
            device_type=plan.netmiko_device_type,
            options=NetmikoConnectionOptions(port=port, timeout=timeout, read_timeout=read_timeout),
        )
    return ParamikoCliTransport(
        plan.device.ip_address,
        credentials,
        port=port,
        timeout=timeout,
        read_timeout=read_timeout,
    )


def selected_transport_label(plan: CommandPlan, preference: TransportPreference = "auto") -> str:
    if preference == "netmiko":
        return f"netmiko:{plan.netmiko_device_type or 'unsupported'}"
    if preference == "paramiko":
        return "paramiko"
    if plan.netmiko_device_type:
        return f"netmiko:{plan.netmiko_device_type}"
    return "paramiko"
