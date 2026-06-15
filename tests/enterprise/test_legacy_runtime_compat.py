from __future__ import annotations

import pytest

from app.core.transport_strategy import DeviceFamily, TransportKind
from netops_orchestrator.drivers.registry import driver_for
from netops_orchestrator.models import Device, VlanChange
from netops_orchestrator.runtime_compat import (
    LegacyRuntimeSafetyError,
    assert_plan_runtime_safe,
    explain_runtime_decision,
    legacy_transport_preference_for_decision,
    runtime_decision_for_device,
    runtime_decision_for_plan,
)


def device(vendor: str, model: str) -> Device:
    return Device(label="sw1", ip_address="192.0.2.1", vendor=vendor, model=model)


def test_runtime_compat_maps_known_devices_and_fails_closed_unknowns() -> None:
    cisco = runtime_decision_for_device(device("Cisco", "Catalyst 2960"))
    huawei = runtime_decision_for_device(device("Huawei", "S5735"))
    huawei_unknown = runtime_decision_for_device(device("Huawei", "Unknown Product"))
    unknown_snmp = runtime_decision_for_device(device("Unknown", "Unknown SNMP Product"))

    assert cisco.family == DeviceFamily.cisco_ios
    assert cisco.selected_transport == TransportKind.netmiko
    assert huawei.family == DeviceFamily.huawei_vrp
    assert huawei.selected_transport == TransportKind.netmiko
    assert huawei_unknown.family == DeviceFamily.unknown
    assert huawei_unknown.selected_transport == TransportKind.unsupported
    assert unknown_snmp.family == DeviceFamily.unknown
    assert unknown_snmp.selected_transport == TransportKind.unsupported


def test_runtime_compat_metadata_cannot_override_explicit_unknown_or_icmp_fail_closed() -> None:
    huawei_unknown = runtime_decision_for_device(
        Device(
            label="bad",
            ip_address="192.0.2.9",
            vendor="Huawei",
            model="Unknown Product",
            metadata={"family": "huawei_vrp", "driver_name": "HuaweiVRPDriver"},
        )
    )
    icmp = runtime_decision_for_device(
        Device(
            label="icmp",
            ip_address="192.0.2.10",
            vendor="Cisco",
            model="ICMP-only",
            metadata={"family": "cisco_ios", "driver_name": "CiscoIOSDriver"},
        )
    )

    assert huawei_unknown.family == DeviceFamily.unknown
    assert huawei_unknown.selected_transport == TransportKind.unsupported
    assert icmp.family == DeviceFamily.icmp
    assert icmp.selected_transport == TransportKind.icmp_only


def test_runtime_compat_generic_icmp_eltex_and_bulat_are_not_config_capable() -> None:
    generic = runtime_decision_for_device(
        Device(
            label="generic",
            ip_address="192.0.2.2",
            vendor="GenericSSH",
            model="Manual",
            metadata={"driver_name": "GenericSSHDriver"},
        )
    )
    icmp = runtime_decision_for_device(device("ICMP-only", "ICMP-only"))
    eltex = runtime_decision_for_device(device("Eltex", "MES2324B"))
    bulat = runtime_decision_for_device(device("Bulat", "BS2500-24G4S"))

    assert generic.family == DeviceFamily.generic_ssh
    assert generic.selected_transport == TransportKind.paramiko
    assert icmp.family == DeviceFamily.icmp
    assert icmp.selected_transport == TransportKind.icmp_only
    assert eltex.selected_transport == TransportKind.custom_cli
    assert bulat.selected_transport == TransportKind.custom_cli
    for decision in (generic, icmp, eltex, bulat):
        assert decision.config_apply_allowed is False
        assert decision.real_apply_certified is False


def test_runtime_compat_blocks_config_plan_and_allows_read_only_backup_plan() -> None:
    backup_plan = driver_for(device("Cisco", "Catalyst 2960")).backup_config()
    config_plan = driver_for(device("Cisco", "Catalyst 2960")).configure_vlan(VlanChange(vlan_id=100, name="USERS"))

    assert_plan_runtime_safe(backup_plan, "backup")
    with pytest.raises(LegacyRuntimeSafetyError, match="Legacy CLI real apply is disabled"):
        assert_plan_runtime_safe(config_plan, "vlan")


def test_runtime_compat_plan_explanation_is_safe_and_deterministic() -> None:
    plan = driver_for(device("Bulat", "BS2500-24G4S")).backup_config()
    decision = runtime_decision_for_plan(plan)
    first = explain_runtime_decision(plan)
    second = explain_runtime_decision(plan)

    assert first == second
    assert decision.family == DeviceFamily.bulat
    assert legacy_transport_preference_for_decision(decision) == "custom_cli"
    assert first["legacy_real_apply_allowed"] is False
    assert first["config_apply_allowed"] is False
