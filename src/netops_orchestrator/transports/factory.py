from __future__ import annotations

from typing import Literal

from app.core.transport_strategy import TransportKind

from ..models import CommandPlan
from ..runtime_compat import LegacyRuntimeSafetyError, assert_plan_runtime_safe, runtime_decision_for_plan
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
    assert_plan_runtime_safe(plan, plan.operation)
    decision = runtime_decision_for_plan(plan)

    if preference == "netmiko":
        if decision.selected_transport != TransportKind.netmiko or not plan.netmiko_device_type:
            raise ValueError(f"Driver {plan.driver} has no Netmiko device_type mapping")
        return _netmiko_transport(plan, credentials, port, timeout, read_timeout)

    if preference == "paramiko":
        if TransportKind.paramiko not in {decision.selected_transport, decision.fallback_transport}:
            raise LegacyRuntimeSafetyError(
                f"Paramiko preference cannot bypass runtime decision {decision.selected_transport.value} "
                f"for {decision.family.value}."
            )
        return _paramiko_transport(plan, credentials, port, timeout, read_timeout)

    if decision.selected_transport == TransportKind.netmiko:
        if not plan.netmiko_device_type:
            raise ValueError(f"Driver {plan.driver} has no Netmiko device_type mapping")
        return _netmiko_transport(plan, credentials, port, timeout, read_timeout)

    if decision.selected_transport == TransportKind.paramiko:
        return _paramiko_transport(plan, credentials, port, timeout, read_timeout)

    if decision.selected_transport == TransportKind.custom_cli and decision.fallback_transport == TransportKind.paramiko:
        return _paramiko_transport(plan, credentials, port, timeout, read_timeout)

    raise LegacyRuntimeSafetyError(
        f"No safe legacy CLI transport is available for {decision.family.value}: "
        f"{decision.unsupported_reason or decision.selected_transport.value}"
    )


def _netmiko_transport(
    plan: CommandPlan,
    credentials: SshCredentials,
    port: int,
    timeout: float,
    read_timeout: float,
) -> NetmikoCliTransport:
    if not plan.netmiko_device_type:
        raise ValueError(f"Driver {plan.driver} has no Netmiko device_type mapping")
    return NetmikoCliTransport(
        plan.device.ip_address,
        credentials,
        device_type=plan.netmiko_device_type,
        options=NetmikoConnectionOptions(port=port, timeout=timeout, read_timeout=read_timeout),
    )


def _paramiko_transport(
    plan: CommandPlan,
    credentials: SshCredentials,
    port: int,
    timeout: float,
    read_timeout: float,
) -> ParamikoCliTransport:
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
    decision = runtime_decision_for_plan(plan)
    if decision.selected_transport == TransportKind.netmiko and plan.netmiko_device_type:
        return f"netmiko:{plan.netmiko_device_type}"
    if decision.selected_transport == TransportKind.icmp_only:
        return "icmp_only"
    if decision.selected_transport == TransportKind.unsupported:
        return "unsupported"
    return "paramiko"
