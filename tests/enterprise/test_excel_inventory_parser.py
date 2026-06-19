from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from app.core.transport_strategy import DeviceFamily, TransportKind
from app.services.driver_capability_matrix import DriverCapabilityMatrix
from app.services.excel_inventory import ExcelInventoryError, load_excel_inventory, resolve_excel_device
from tests.enterprise.excel_lab_helpers import EXCEL_HEADERS, write_inventory


def test_excel_inventory_parses_user_columns_and_runtime_hints(tmp_path: Path) -> None:
    path = write_inventory(
        tmp_path / "inventory.xlsx",
        [
            ["Active", "huawei-lab", "S5720", "192.0.2.67", "HUAWEI", "Switch", "Lab", "NetOps"],
            ["Active", "hpe-lab", "1910", "192.0.2.68", "Hewlett Packard", "Switch", "Lab", "NetOps"],
            ["Active", "eltex-lab", "MES2448", "192.0.2.69", "Eltex", "Switch", "Lab", "NetOps"],
            ["Active", "bulat-lab", "BS2500", "192.0.2.70", "Bulat", "Switch", "Lab", "NetOps"],
            ["Active", "unknown-lab", "Unknown SNMP Product", "192.0.2.71", "Huawei", "Switch", "Lab", "NetOps"],
            ["Service", "service-row", "n/a", "192.0.2.72", "n/a", "Service", "Lab", "NetOps"],
        ],
    )

    devices = load_excel_inventory(path)

    assert len(devices) == 5
    assert devices[0].driver_name == "HuaweiVRPDriver"
    assert devices[1].driver_name == "HPComwareDriver"
    assert devices[2].driver_name == "EltexMESDriver"
    assert devices[3].driver_name == "BulatBSDriver"
    assert devices[4].driver_name is None
    assert resolve_excel_device(devices, "192.0.2.67").label == "huawei-lab"
    assert resolve_excel_device(devices, devices[0].id).label == "huawei-lab"


def test_excel_inventory_missing_columns_and_duplicate_selector_are_friendly(tmp_path: Path) -> None:
    broken = tmp_path / "broken.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(EXCEL_HEADERS[:-1])
    workbook.save(broken)
    workbook.close()

    try:
        load_excel_inventory(broken)
    except ExcelInventoryError as exc:
        assert "missing required column" in str(exc).casefold()
    else:
        raise AssertionError("Missing Excel columns were not rejected")

    duplicated = write_inventory(
        tmp_path / "duplicated.xlsx",
        [
            ["Active", "same-label", "Catalyst 2960", "192.0.2.67", "Cisco", "Switch", "Lab", "NetOps"],
            ["Active", "same-label", "Catalyst 2960", "192.0.2.68", "Cisco", "Switch", "Lab", "NetOps"],
        ],
    )
    devices = load_excel_inventory(duplicated)
    try:
        resolve_excel_device(devices, "same-label")
    except ExcelInventoryError as exc:
        assert "multiple rows" in str(exc).casefold()
    else:
        raise AssertionError("Duplicate Excel selector was not rejected")


def test_excel_unknown_vendor_cannot_be_upgraded_to_a_candidate_by_model_hints(tmp_path: Path) -> None:
    device = load_excel_inventory(
        write_inventory(
            tmp_path / "unknown-vendor.xlsx",
            [["Active", "unknown-cisco", "Catalyst 2960", "192.0.2.99", "Unknown", "Switch", "Lab", "NetOps"]],
        )
    )[0]

    decision = DriverCapabilityMatrix().decide(
        vendor=device.vendor,
        model=device.model,
        platform=device.platform,
        driver_name=device.driver_name,
    )

    assert device.driver_name == "CiscoIOSDriver"
    assert decision.family == DeviceFamily.unknown
    assert decision.selected_transport == TransportKind.unsupported
