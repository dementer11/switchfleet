from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook

from app.services.inventory_parser import InventoryParser


def test_inventory_parser_parses_csv_json_and_xlsx() -> None:
    parser = InventoryParser()
    csv_rows = parser.parse_csv_text("ip,hostname,vendor,model,tags\n10.0.0.1,sw1,Huawei,S5735,\"core,access\"\n")
    json_rows = parser.parse_json_text('[{"ip":"10.0.0.2","hostname":"sw2","vendor":"Cisco","model":"Cat2960"}]')
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["management_ip", "host", "manufacturer", "model"])
    sheet.append(["10.0.0.3", "sw3", "Dell", "PowerConnect 3524"])
    content = BytesIO()
    workbook.save(content)
    xlsx_rows = parser.parse_xlsx_bytes(content.getvalue())

    assert csv_rows[0]["management_ip"] == "10.0.0.1"
    assert json_rows[0]["hostname"] == "sw2"
    assert xlsx_rows[0]["vendor"] == "Dell"


def test_inventory_parser_rejects_non_list_json() -> None:
    parser = InventoryParser()

    try:
        parser.parse_json_text('{"ip":"10.0.0.1"}')
    except ValueError as exc:
        assert "list" in str(exc)
    else:
        raise AssertionError("Expected non-list JSON payload to be rejected")
