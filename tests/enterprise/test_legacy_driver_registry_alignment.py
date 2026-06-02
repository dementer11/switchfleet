from __future__ import annotations

from app.core.transport_strategy import DeviceFamily
from netops_orchestrator.drivers.registry import driver_for
from netops_orchestrator.models import Device
from netops_orchestrator.runtime_compat import runtime_decision_for_device


def device(vendor: str, model: str) -> Device:
    return Device(label="sw1", ip_address="10.0.0.1", vendor=vendor, model=model)


def test_legacy_registry_aligns_with_matrix_for_known_supported_models() -> None:
    cases = [
        (device("Cisco", "Catalyst 2960"), DeviceFamily.cisco_ios, "cisco_ios"),
        (device("Huawei", "S5735-L48T4X-A1"), DeviceFamily.huawei_vrp, "huawei_vrp"),
        (device("HPE", "5130-48G-4SFP+ EI"), DeviceFamily.hpe_comware, "comware7"),
        (device("HPE", "2530-8G-PoE+"), DeviceFamily.hpe_procurve, "hpe_procurve"),
        (device("Dell", "PowerConnect 3524"), DeviceFamily.dell_os, "dell_powerconnect"),
        (device("Eltex", "MES2448B"), DeviceFamily.eltex, "eltex_mes"),
        (device("Bulat", "BS2500-48G4S-A"), DeviceFamily.bulat, "bulat_bs"),
    ]

    for dev, expected_family, expected_driver in cases:
        decision = runtime_decision_for_device(dev)
        driver = driver_for(dev)

        assert decision.family == expected_family
        assert driver.name == expected_driver


def test_legacy_registry_fails_closed_for_unknown_icmp_and_generic_profiles() -> None:
    cases = [
        device("Huawei", "Unknown Product"),
        device("Unknown", "Unknown SNMP Product"),
        device("ICMP-only", "ICMP-only"),
        Device(
            label="bad",
            ip_address="10.0.0.3",
            vendor="Huawei",
            model="Unknown Product",
            metadata={"family": "huawei_vrp", "driver_name": "HuaweiVRPDriver"},
        ),
        Device(
            label="icmp",
            ip_address="10.0.0.4",
            vendor="Cisco",
            model="ICMP-only",
            metadata={"family": "cisco_ios", "driver_name": "CiscoIOSDriver"},
        ),
        Device(
            label="generic",
            ip_address="10.0.0.2",
            vendor="GenericSSH",
            model="Manual",
            metadata={"driver_name": "GenericSSHDriver"},
        ),
    ]

    for dev in cases:
        assert driver_for(dev).name == "unsupported_cli"


def test_legacy_registry_keeps_non_matrix_qtech_planning_without_config_apply_runtime() -> None:
    dev = device("QTECH", "QSW-4610-52T-AC")
    decision = runtime_decision_for_device(dev)
    driver = driver_for(dev)

    assert decision.family == DeviceFamily.unknown
    assert driver.name == "qtech_qsw"
