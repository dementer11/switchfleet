from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook


EXCEL_HEADERS = ["Status", "Device Label", "Model", "IP Address", "Vendor", "Device Category", "Location", "Contact"]


def write_inventory(path: Path, rows: list[list[str]] | None = None) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(EXCEL_HEADERS)
    for row in rows or [["Active", "sw1-lab", "Catalyst 2960", "10.13.4.67", "Cisco", "Switch", "Lab", "NetOps"]]:
        sheet.append(row)
    workbook.save(path)
    workbook.close()
    return path
