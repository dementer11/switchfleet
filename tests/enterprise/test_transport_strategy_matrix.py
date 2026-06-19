from __future__ import annotations

import pytest

from app.core.transport_strategy import DeviceFamily, TransportKind
from app.services.driver_capability_matrix import DriverCapabilityMatrix


@pytest.mark.parametrize(
    ("vendor", "model", "platform", "expected_family", "expected_transport"),
    [
        ("Cisco", "Catalyst 2960", "ios", DeviceFamily.cisco_ios, TransportKind.netmiko),
        ("Cisco", "Nexus 9300", "nxos", DeviceFamily.cisco_nxos, TransportKind.netmiko),
        ("Cisco", "ASA 5525", "asa", DeviceFamily.cisco_asa, TransportKind.netmiko),
        ("Huawei", "S5735-L48T4X-A1", "vrp", DeviceFamily.huawei_vrp, TransportKind.netmiko),
        ("HPE", "5130-48G-4SFP+ EI", "comware", DeviceFamily.hpe_comware, TransportKind.netmiko),
        ("HPE", "S4210", "", DeviceFamily.hpe_comware, TransportKind.netmiko),
        ("HPE", "S5500", "", DeviceFamily.hpe_comware, TransportKind.netmiko),
        ("HPE", "2530-8G-PoE+", "procurve", DeviceFamily.hpe_procurve, TransportKind.netmiko),
        ("Aruba", "2930F", "aruba_os_switch", DeviceFamily.aruba_os_switch, TransportKind.netmiko),
        ("QTECH", "QSW-4610", "qtech", DeviceFamily.qtech, TransportKind.custom_cli),
        ("Dell", "PowerConnect 3524", "dell", DeviceFamily.dell_os, TransportKind.netmiko),
        ("HPE", "1820", "limited_web", DeviceFamily.limited_web, TransportKind.unsupported),
        ("SecurityCode", "Continent-500", "non_switch", DeviceFamily.non_switch, TransportKind.unsupported),
        ("Eltex", "MES2324B", "eltex", DeviceFamily.eltex, TransportKind.custom_cli),
        ("Bulat", "BS2500-24G4S", "bulat", DeviceFamily.bulat, TransportKind.custom_cli),
        ("GenericSSH", "Manual profile", "generic", DeviceFamily.generic_ssh, TransportKind.paramiko),
        ("ICMP-only", "ICMP-only", "icmp-only", DeviceFamily.icmp, TransportKind.icmp_only),
        ("Unknown", "Unknown", "", DeviceFamily.unknown, TransportKind.unsupported),
    ],
)
def test_driver_capability_matrix_selects_expected_runtime_profiles(
    vendor: str,
    model: str,
    platform: str,
    expected_family: DeviceFamily,
    expected_transport: TransportKind,
) -> None:
    decision = DriverCapabilityMatrix().decide(vendor=vendor, model=model, platform=platform)

    assert decision.family == expected_family
    assert decision.selected_transport == expected_transport
    assert decision.config_apply_allowed is False
    assert decision.real_apply_certified is False


def test_generic_icmp_unknown_and_uncertified_vendor_decisions_fail_safely() -> None:
    matrix = DriverCapabilityMatrix()

    generic = matrix.decide(vendor="GenericSSH", model="Manual profile", driver_name="GenericSSHDriver")
    huawei_unknown = matrix.decide(vendor="Huawei", model="Unknown Product")
    ambiguous_huawei = matrix.decide(vendor="Huawei", model="Unknown Router")
    unknown_snmp = matrix.decide(vendor="Unknown", model="Unknown SNMP Product")
    icmp = matrix.decide(vendor="ICMP", model="ICMP-only")
    unknown = matrix.decide(vendor="MysteryVendor", model="MysteryBox")
    bulat = matrix.decide(vendor="Bulat", model="BS6300")
    eltex = matrix.decide(vendor="Eltex", model="MES2448B")

    assert generic.family == DeviceFamily.generic_ssh
    assert generic.config_apply_allowed is False
    assert any("Generic SSH" in warning for warning in generic.safety_warnings)
    assert huawei_unknown.family == DeviceFamily.unknown
    assert huawei_unknown.selected_transport == TransportKind.unsupported
    assert huawei_unknown.unsupported_reason
    assert ambiguous_huawei.family == DeviceFamily.unknown
    assert ambiguous_huawei.selected_transport == TransportKind.unsupported
    assert unknown_snmp.family == DeviceFamily.unknown
    assert unknown_snmp.selected_transport == TransportKind.unsupported
    assert unknown_snmp.unsupported_reason
    assert icmp.family == DeviceFamily.icmp
    assert icmp.read_only_allowed is True
    assert icmp.config_apply_allowed is False
    assert unknown.family == DeviceFamily.unknown
    assert unknown.unsupported_reason
    assert bulat.config_apply_allowed is False
    assert eltex.config_apply_allowed is False


def test_hard_fail_closed_profiles_cannot_be_overridden_by_metadata() -> None:
    matrix = DriverCapabilityMatrix()

    huawei_unknown_driver = matrix.decide(vendor="Huawei", model="Unknown Product", driver_name="HuaweiVRPDriver")
    huawei_unknown_family = matrix.decide(vendor="Huawei", model="Unknown SNMP Product", family=DeviceFamily.huawei_vrp)
    icmp_driver = matrix.decide(vendor="ICMP", model="ICMP-only", driver_name="CiscoIOSDriver")
    icmp_family = matrix.decide(vendor="ICMP", model="ICMP-only", family=DeviceFamily.cisco_ios)
    dlink_driver = matrix.decide(vendor="D-Link", model="DES1100", driver_name="CiscoIOSDriver")
    dlink_family = matrix.decide(vendor="D-Link", model="DES1100", family=DeviceFamily.cisco_ios)
    security_driver = matrix.decide(vendor="SecurityCode", model="Continent-500", driver_name="CiscoIOSDriver")
    security_family = matrix.decide(vendor="SecurityCode", model="Continent-500", family=DeviceFamily.cisco_ios)
    unknown_cisco_driver = matrix.decide(vendor="Unknown", model="Catalyst 2960", driver_name="CiscoIOSDriver")
    unknown_comware_family = matrix.decide(vendor="SNMP Unknown", model="HPE 1910", family=DeviceFamily.hpe_comware)

    assert huawei_unknown_driver.family == DeviceFamily.unknown
    assert huawei_unknown_driver.selected_transport == TransportKind.unsupported
    assert huawei_unknown_family.family == DeviceFamily.unknown
    assert huawei_unknown_family.selected_transport == TransportKind.unsupported
    assert icmp_driver.family == DeviceFamily.icmp
    assert icmp_driver.selected_transport == TransportKind.icmp_only
    assert icmp_family.family == DeviceFamily.icmp
    assert icmp_family.selected_transport == TransportKind.icmp_only
    assert dlink_driver.family == DeviceFamily.limited_web
    assert dlink_driver.selected_transport == TransportKind.unsupported
    assert dlink_family.family == DeviceFamily.limited_web
    assert dlink_family.selected_transport == TransportKind.unsupported
    assert security_driver.family == DeviceFamily.non_switch
    assert security_driver.selected_transport == TransportKind.unsupported
    assert security_family.family == DeviceFamily.non_switch
    assert security_family.selected_transport == TransportKind.unsupported
    assert unknown_cisco_driver.family == DeviceFamily.unknown
    assert unknown_cisco_driver.selected_transport == TransportKind.unsupported
    assert unknown_comware_family.family == DeviceFamily.unknown
    assert unknown_comware_family.selected_transport == TransportKind.unsupported
    assert all(
        decision.config_apply_allowed is False
        for decision in (
            huawei_unknown_driver,
            huawei_unknown_family,
            icmp_driver,
            icmp_family,
            dlink_driver,
            dlink_family,
            security_driver,
            security_family,
            unknown_cisco_driver,
            unknown_comware_family,
        )
    )
