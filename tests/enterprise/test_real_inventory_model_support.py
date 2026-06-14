from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.core.transport_strategy import DeviceFamily, TransportKind
from app.services.driver_capability_matrix import DriverCapabilityMatrix
from app.services.excel_inventory import load_excel_inventory
from tests.enterprise.excel_lab_helpers import write_inventory


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "real_inventory_models.csv"

EXPECTED_REAL_INVENTORY_FAMILIES: dict[str, tuple[DeviceFamily, TransportKind]] = {
    "huawei-s5735": (DeviceFamily.huawei_vrp, TransportKind.netmiko),
    "huawei-s5731": (DeviceFamily.huawei_vrp, TransportKind.netmiko),
    "huawei-s5732": (DeviceFamily.huawei_vrp, TransportKind.netmiko),
    "huawei-s5720": (DeviceFamily.huawei_vrp, TransportKind.netmiko),
    "huawei-s5700": (DeviceFamily.huawei_vrp, TransportKind.netmiko),
    "huawei-s6730": (DeviceFamily.huawei_vrp, TransportKind.netmiko),
    "huawei-ce6855": (DeviceFamily.huawei_vrp, TransportKind.netmiko),
    "huawei-s1720": (DeviceFamily.huawei_vrp, TransportKind.netmiko),
    "huawei-s2309": (DeviceFamily.huawei_vrp, TransportKind.netmiko),
    "huawei-s2403": (DeviceFamily.huawei_vrp, TransportKind.netmiko),
    "hpe-1910": (DeviceFamily.hpe_comware, TransportKind.netmiko),
    "hpe-1920": (DeviceFamily.hpe_comware, TransportKind.netmiko),
    "hpe-5130": (DeviceFamily.hpe_comware, TransportKind.netmiko),
    "3com-s4210": (DeviceFamily.hpe_comware, TransportKind.netmiko),
    "3com-s5500": (DeviceFamily.hpe_comware, TransportKind.netmiko),
    "hpe-2510": (DeviceFamily.hpe_procurve, TransportKind.netmiko),
    "hpe-2530": (DeviceFamily.hpe_procurve, TransportKind.netmiko),
    "hpe-1620": (DeviceFamily.limited_web, TransportKind.unsupported),
    "hpe-1820": (DeviceFamily.limited_web, TransportKind.unsupported),
    "hpe-1905": (DeviceFamily.limited_web, TransportKind.unsupported),
    "qtech-4610": (DeviceFamily.qtech, TransportKind.custom_cli),
    "qtech-3750": (DeviceFamily.qtech, TransportKind.custom_cli),
    "eltex-2324": (DeviceFamily.eltex, TransportKind.custom_cli),
    "eltex-2348": (DeviceFamily.eltex, TransportKind.custom_cli),
    "eltex-2448": (DeviceFamily.eltex, TransportKind.custom_cli),
    "bulat-2500": (DeviceFamily.bulat, TransportKind.custom_cli),
    "bulat-6300": (DeviceFamily.bulat, TransportKind.custom_cli),
    "bulat-bk": (DeviceFamily.bulat, TransportKind.custom_cli),
    "dell-3524": (DeviceFamily.dell_os, TransportKind.netmiko),
    "cisco-2960": (DeviceFamily.cisco_ios, TransportKind.netmiko),
    "cisco-37xx": (DeviceFamily.cisco_ios, TransportKind.netmiko),
    "dlink-des1100": (DeviceFamily.limited_web, TransportKind.unsupported),
    "continent-500": (DeviceFamily.non_switch, TransportKind.unsupported),
    "unknown-snmp": (DeviceFamily.unknown, TransportKind.unsupported),
    "icmp-only": (DeviceFamily.icmp, TransportKind.icmp_only),
}


def real_inventory_rows() -> list[list[str]]:
    with FIXTURE_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        next(reader)
        return [row for row in reader]


def test_real_inventory_fixture_covers_every_requested_model_with_expected_family(tmp_path: Path) -> None:
    devices = load_excel_inventory(write_inventory(tmp_path / "real-inventory.xlsx", real_inventory_rows()))
    assert {device.label for device in devices} == set(EXPECTED_REAL_INVENTORY_FAMILIES)

    for device in devices:
        expected_family, expected_transport = EXPECTED_REAL_INVENTORY_FAMILIES[device.label]
        decision = DriverCapabilityMatrix().decide(
            vendor=device.vendor,
            model=device.model,
            platform=device.platform,
            driver_name=device.driver_name,
            device_id=device.id,
            hostname=device.hostname,
        )

        assert decision.family == expected_family, device.label
        assert decision.selected_transport == expected_transport, device.label
        assert decision.config_apply_allowed is False
        assert decision.real_apply_certified is False


@pytest.mark.parametrize(
    ("label", "family", "transport"),
    [
        ("huawei-s5735", DeviceFamily.huawei_vrp, TransportKind.netmiko),
        ("huawei-ce6855", DeviceFamily.huawei_vrp, TransportKind.netmiko),
        ("hpe-1910", DeviceFamily.hpe_comware, TransportKind.netmiko),
        ("3com-s5500", DeviceFamily.hpe_comware, TransportKind.netmiko),
        ("hpe-2530", DeviceFamily.hpe_procurve, TransportKind.netmiko),
        ("hpe-1820", DeviceFamily.limited_web, TransportKind.unsupported),
        ("qtech-4610", DeviceFamily.qtech, TransportKind.custom_cli),
        ("eltex-2448", DeviceFamily.eltex, TransportKind.custom_cli),
        ("bulat-bk", DeviceFamily.bulat, TransportKind.custom_cli),
        ("dell-3524", DeviceFamily.dell_os, TransportKind.netmiko),
        ("cisco-2960", DeviceFamily.cisco_ios, TransportKind.netmiko),
        ("dlink-des1100", DeviceFamily.limited_web, TransportKind.unsupported),
        ("continent-500", DeviceFamily.non_switch, TransportKind.unsupported),
        ("unknown-snmp", DeviceFamily.unknown, TransportKind.unsupported),
        ("icmp-only", DeviceFamily.icmp, TransportKind.icmp_only),
    ],
)
def test_real_inventory_sample_maps_models_to_safe_runtime_profiles(
    tmp_path: Path,
    label: str,
    family: DeviceFamily,
    transport: TransportKind,
) -> None:
    devices = load_excel_inventory(write_inventory(tmp_path / "real-inventory.xlsx", real_inventory_rows()))
    device = next(item for item in devices if item.label == label)
    decision = DriverCapabilityMatrix().decide(
        vendor=device.vendor,
        model=device.model,
        platform=device.platform,
        driver_name=device.driver_name,
        device_id=device.id,
        hostname=device.hostname,
    )

    assert decision.family == family
    assert decision.selected_transport == transport
    assert decision.config_apply_allowed is False
    assert decision.real_apply_certified is False
    assert device.original_vendor
    assert device.original_model
    assert device.normalized_vendor == device.vendor
    assert device.normalized_model == device.model


def test_real_inventory_sample_keeps_candidate_and_unsupported_apply_blocked(tmp_path: Path) -> None:
    devices = load_excel_inventory(write_inventory(tmp_path / "real-inventory.xlsx", real_inventory_rows()))
    decisions = [
        DriverCapabilityMatrix().decide(
            vendor=device.vendor,
            model=device.model,
            platform=device.platform,
            driver_name=device.driver_name,
            device_id=device.id,
            hostname=device.hostname,
        )
        for device in devices
    ]

    assert {decision.family for decision in decisions} >= {
        DeviceFamily.qtech,
        DeviceFamily.limited_web,
        DeviceFamily.non_switch,
    }
    assert all(decision.config_apply_allowed is False for decision in decisions)
    assert all(decision.real_apply_certified is False for decision in decisions)


def test_packaged_lab_example_inventory_parses_runtime_classifications() -> None:
    example = Path(__file__).resolve().parents[2] / "examples" / "lab" / "inventory.example.xlsx"
    devices = load_excel_inventory(example)
    decisions = {
        device.label: DriverCapabilityMatrix().decide(
            vendor=device.vendor,
            model=device.model,
            platform=device.platform,
            driver_name=device.driver_name,
            device_id=device.id,
            hostname=device.hostname,
        )
        for device in devices
    }

    assert decisions["huawei-s5735"].family == DeviceFamily.huawei_vrp
    assert decisions["hpe-1910"].family == DeviceFamily.hpe_comware
    assert decisions["hpe-2530"].family == DeviceFamily.hpe_procurve
    assert decisions["qtech-4610"].family == DeviceFamily.qtech
    assert decisions["dlink-des1100"].family == DeviceFamily.limited_web
    assert decisions["continent-500"].family == DeviceFamily.non_switch
    assert decisions["unknown-snmp"].family == DeviceFamily.unknown
    assert decisions["icmp-only"].family == DeviceFamily.icmp
    assert decisions["icmp-only"].selected_transport == TransportKind.icmp_only
    assert all(decision.config_apply_allowed is False for decision in decisions.values())
