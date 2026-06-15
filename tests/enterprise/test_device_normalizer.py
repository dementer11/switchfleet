from __future__ import annotations

import pytest

from app.services.device_normalizer import normalize_inventory_record


@pytest.mark.parametrize(
    ("vendor", "model", "expected_vendor", "expected_platform"),
    [
        ("Huawei", "S5735-L48T4X-A1", "Huawei", "vrp"),
        ("Huawei", "CE6855-48T6Q-HI", "Huawei", "vrp"),
        ("Cisco", "Cat2960-48", "Cisco", "ios"),
        ("Cisco", "Catalyst 37xxStack", "Cisco", "ios"),
        ("HPE", "HPE 1910-24G", "HPE", "comware"),
        ("HPE", "HPE 2530-8G-PoE+", "HPE", "procurve"),
        ("3Com", "3Com S5500-52-EI", "3Com", "comware"),
        ("3Com", "3Com S4210 26-Port", "3Com", "comware"),
        ("Eltex", "MES2448B", "Eltex", "eltex-mes"),
        ("Bulat", "BS2500-48G4S-A", "Bulat", "bulat-bs"),
        ("QSW", "QSW-4610-28T-AC", "QSW", "qsw"),
        ("Dell", "PowerConnect 3524", "Dell", "powerconnect"),
        ("D-Link", "DES1100-16", "D-Link", "d-link"),
        ("Continent", "Continent-500", "Continent", "continent"),
        ("Unknown SNMP Product", "Unknown SNMP Product", "Unknown SNMP", "unknown"),
        ("ICMP-only", "ICMP-only", "ICMP", "icmp-only"),
    ],
)
def test_device_normalizer_known_families(
    vendor: str,
    model: str,
    expected_vendor: str,
    expected_platform: str,
) -> None:
    normalized = normalize_inventory_record(
        {
            "ip": "192.0.2.1",
            "hostname": "sw",
            "vendor": vendor,
            "model": model,
            "tags": "core, access",
        }
    )

    assert normalized.valid is True
    assert normalized.data["normalized_vendor"] == expected_vendor
    assert normalized.data["platform"] == expected_platform
    assert normalized.data["tags"] == ["access", "core"]


def test_device_normalizer_missing_ip_and_bad_ip() -> None:
    missing = normalize_inventory_record({"hostname": "sw1", "vendor": "Huawei", "model": "S5735"})
    bad = normalize_inventory_record({"ip": "not-an-ip", "vendor": "Huawei", "model": "S5735"})

    assert missing.valid is False
    assert "management_ip is required" in missing.errors
    assert bad.valid is False
    assert "Invalid management_ip" in bad.errors[0]
