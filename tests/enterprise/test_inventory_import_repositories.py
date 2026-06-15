from __future__ import annotations

from app.db.session import SessionLocal
from app.repositories.device_inventory import DeviceInventoryRepository
from app.repositories.inventory_imports import InventoryImportRepository


def test_inventory_import_repository_batch_rows_and_statuses() -> None:
    session = SessionLocal()
    imports = InventoryImportRepository(session)
    batch = imports.create_batch(source_type="api", filename="inventory.json", requested_by="operator")
    rows = imports.add_rows(batch.id, [{"management_ip": "192.0.2.1"}, {"management_ip": ""}])

    imports.mark_row_valid(rows[0].id, {"management_ip": "192.0.2.1"})
    imports.mark_row_invalid(rows[1].id, "management_ip is required")
    finished = imports.finish_batch(batch.id, "validated")

    assert finished.total_rows == 2
    assert finished.valid_rows == 1
    assert finished.invalid_rows == 1
    assert [row.row_index for row in imports.list_rows(batch.id)] == [1, 2]


def test_device_inventory_repository_upsert_duplicates_site_and_tag() -> None:
    session = SessionLocal()
    repository = DeviceInventoryRepository(session)
    data = {
        "management_ip": "192.0.2.10",
        "hostname": "sw-core-1",
        "vendor": "Huawei",
        "model": "S5735",
        "normalized_vendor": "Huawei",
        "normalized_model": "S5735",
        "platform": "vrp",
        "site": "HQ",
        "tags": ["core", "aggregation"],
    }

    created, was_created = repository.upsert_device(data)
    updated, was_updated_created = repository.upsert_device({**data, "location": "MDF"})

    assert was_created is True
    assert was_updated_created is False
    assert created.id == updated.id
    assert repository.find_by_management_ip("192.0.2.10") is not None
    assert repository.find_by_hostname("sw-core-1") is not None
    assert len(repository.find_duplicates(management_ip="192.0.2.10", hostname="sw-core-1")) == 1
    assert repository.list_by_site("HQ")[0].id == created.id
    assert repository.list_by_tag("core")[0].id == created.id
