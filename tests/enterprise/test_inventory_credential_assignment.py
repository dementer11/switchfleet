from __future__ import annotations

from uuid import uuid4

from app.db.session import SessionLocal
from app.schemas.credential import CredentialCreate
from app.schemas.inventory import InventoryImportRequest
from app.services.credential_service import CredentialService
from app.services.inventory_validation_service import InventoryValidationService


def test_inventory_credential_assignment_found_and_missing_are_safe() -> None:
    session = SessionLocal()
    secret = f"runtime-secret-{uuid4().hex}"
    CredentialService(session).create(CredentialCreate(name="core-ssh", username="netops", password=secret), actor="sec")
    response = InventoryValidationService(session).import_inventory(
        InventoryImportRequest(
            source_type="api",
            dry_run=False,
            strict=False,
            items=[
                {
                    "ip": "10.2.0.1",
                    "hostname": "sw1",
                    "vendor": "Cisco",
                    "model": "Cat2960-48",
                    "credential_name": "core-ssh",
                },
                {
                    "ip": "10.2.0.2",
                    "hostname": "sw2",
                    "vendor": "Cisco",
                    "model": "Cat2960-48",
                    "credential_name": "missing-ssh",
                },
            ],
        ),
        actor="netadmin",
    )

    credentials = {item.hostname: item.credential for item in response.validation_report.items}
    missing_item = next(item for item in response.validation_report.items if item.hostname == "sw2")
    assert credentials["sw1"].status == "assigned"
    assert credentials["sw1"].username == "netops"
    assert credentials["sw2"].status == "missing"
    assert any("missing-ssh" in warning for warning in missing_item.warnings)
    assert any("missing-ssh" in warning for warning in response.validation_report.warnings)
    assert secret not in response.model_dump_json()


def test_inventory_strict_mode_marks_missing_credential_invalid() -> None:
    response = InventoryValidationService(SessionLocal()).import_inventory(
        InventoryImportRequest(
            source_type="api",
            dry_run=True,
            strict=True,
            items=[
                {
                    "ip": "10.2.1.1",
                    "hostname": "sw1",
                    "vendor": "Cisco",
                    "model": "Cat2960-48",
                    "credential_name": "missing-ssh",
                }
            ],
        ),
        actor="netadmin",
    )

    assert response.batch.invalid_rows == 1
    assert response.validation_report.items[0].row_status == "invalid"
