from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.device import Device
from app.db.models.inventory import InventoryImportBatch, InventoryImportRow
from app.db.session import SessionLocal
from app.drivers.generic_ssh import GenericSSHDriver
from app.drivers.readonly_icmp import ReadOnlyICMPDriver
from app.repositories.credentials import CredentialRepository
from app.repositories.device_inventory import DeviceInventoryRepository, tag_labels
from app.repositories.inventory_imports import InventoryImportRepository
from app.schemas.device import DeviceInput
from app.schemas.inventory import (
    CredentialSafeMetadata,
    DriverResolutionItem,
    DriverResolutionReport,
    InventoryDeviceRead,
    InventoryImportBatchRead,
    InventoryImportRequest,
    InventoryImportResponse,
    InventoryImportRowRead,
    InventoryValidationItem,
    InventoryValidationReport,
)
from app.services.device_normalizer import normalize_inventory_record
from app.services.driver_resolver import DriverResolverService
from app.services.inventory_parser import InventoryParser


class InventoryValidationService:
    def __init__(
        self,
        session: Session | None = None,
        parser: InventoryParser | None = None,
        resolver: DriverResolverService | None = None,
    ):
        self.session = session or SessionLocal()
        self.imports = InventoryImportRepository(self.session)
        self.devices = DeviceInventoryRepository(self.session)
        self.credentials = CredentialRepository(self.session)
        self.parser = parser or InventoryParser()
        self.resolver = resolver or DriverResolverService()

    def import_inventory(self, payload: InventoryImportRequest, actor: str) -> InventoryImportResponse:
        batch = self.imports.create_batch(
            source_type=payload.source_type,
            filename=payload.filename,
            requested_by=actor,
        )
        rows = self.imports.add_rows(batch.id, self.parser.parse_items(payload.items))
        self.imports.update_batch_status(batch.id, "parsed")
        for row in rows:
            self._process_row(row, strict=payload.strict, dry_run=payload.dry_run)
        final_status = "validated" if payload.dry_run else "imported"
        batch = self.imports.finish_batch(batch.id, final_status)
        return InventoryImportResponse(
            batch=read_batch(batch),
            dry_run=payload.dry_run,
            validation_report=self.build_inventory_validation_report(str(batch.id), dry_run=payload.dry_run),
        )

    def validate_import_batch(self, batch_id: str) -> InventoryValidationReport:
        for row in self.imports.list_rows(batch_id):
            if row.status in {"created", "updated"}:
                continue
            self._process_row(row, strict=False, dry_run=True)
        self.imports.finish_batch(batch_id, "validated")
        return self.build_inventory_validation_report(batch_id, dry_run=True)

    def resolve_drivers_for_batch(self, batch_id: str) -> DriverResolutionReport:
        items = [self._build_driver_item(row) for row in self.imports.list_rows(batch_id)]
        for item in items:
            if item.device_id:
                self.devices.update_driver_resolution(
                    item.device_id,
                    item.driver_name,
                    item.driver_resolution_status,
                    capabilities=self._capabilities_for_item(item),
                )
        return DriverResolutionReport(batch_id=batch_id, devices=items)

    def validate_credentials_for_batch(self, batch_id: str, strict: bool = False) -> InventoryValidationReport:
        for row in self.imports.list_rows(batch_id):
            normalized = dict(row.normalized_data or {})
            credential = self._credential_metadata(normalized.get("credential_name"))
            normalized["credential"] = credential.model_dump()
            if strict and credential.status == "missing" and row.status != "invalid":
                self.imports.mark_row_invalid(row.id, "Credential not found", normalized)
            else:
                self.imports.mark_row_valid(row.id, normalized)
        self.imports.finish_batch(batch_id, "validated")
        return self.build_inventory_validation_report(batch_id, dry_run=True)

    def build_inventory_validation_report(self, batch_id: str, dry_run: bool | None = None) -> InventoryValidationReport:
        batch = self.imports.get_batch(batch_id)
        rows = self.imports.list_rows(batch_id)
        items = [self._build_validation_item(row) for row in rows]
        warnings: list[str] = []
        for item in items:
            warnings.extend(item.warnings)
        return InventoryValidationReport(
            batch_id=str(batch.id),
            total_rows=batch.total_rows,
            valid_rows=batch.valid_rows,
            invalid_rows=batch.invalid_rows,
            created_devices=batch.created_devices,
            updated_devices=batch.updated_devices,
            dry_run=batch.status != "imported" if dry_run is None else dry_run,
            items=items,
            warnings=sorted(set(warnings)),
        )

    def list_batches(self) -> list[InventoryImportBatchRead]:
        return [read_batch(batch) for batch in self.imports.list_batches()]

    def get_batch(self, batch_id: str) -> InventoryImportBatchRead:
        return read_batch(self.imports.get_batch(batch_id))

    def list_rows(self, batch_id: str) -> list[InventoryImportRowRead]:
        return [read_row(row) for row in self.imports.list_rows(batch_id)]

    def list_devices(self, site: str | None = None, tag: str | None = None) -> list[InventoryDeviceRead]:
        if site is not None:
            devices = self.devices.list_by_site(site)
        elif tag is not None:
            devices = self.devices.list_by_tag(tag)
        else:
            devices = self.devices.list_devices()
        return [read_inventory_device(device) for device in devices]

    def get_device(self, device_id: str) -> InventoryDeviceRead:
        return read_inventory_device(self.devices.get(device_id))

    def patch_device_metadata(
        self,
        device_id: str,
        site: str | None = None,
        location: str | None = None,
        rack: str | None = None,
        role: str | None = None,
        tags: list[str] | None = None,
        credential_name: str | None = None,
    ) -> InventoryDeviceRead:
        device = self.devices.patch_metadata(
            device_id,
            site=site,
            location=location,
            rack=rack,
            role=role,
            tags=tags,
        )
        if credential_name is not None:
            credential = self.credentials.get_by_name(credential_name)
            if credential is None:
                self.devices.update_credential_assignment_status(device.id, "invalid")
            else:
                self.credentials.create_assignment(credential.id, device_id=device.id, vendor=device.vendor, site=device.site)
                self.devices.update_credential_assignment_status(device.id, "assigned")
        return read_inventory_device(device)

    def build_driver_resolution_report(self, batch_id: str) -> DriverResolutionReport:
        return DriverResolutionReport(
            batch_id=batch_id,
            devices=[self._build_driver_item(row) for row in self.imports.list_rows(batch_id)],
        )

    def _process_row(self, row: InventoryImportRow, strict: bool, dry_run: bool) -> None:
        normalized = normalize_inventory_record(row.raw_data)
        data = dict(normalized.data)
        if not normalized.valid:
            self.imports.mark_row_invalid(row.id, "; ".join(normalized.errors), data)
            return
        driver_item = self._resolve_driver(data, row_id=str(row.id), device_id=None)
        data.update(
            {
                "driver_name": driver_item.driver_name,
                "driver_resolution_status": driver_item.driver_resolution_status,
                "capabilities": self._capabilities_for_item(driver_item),
                "apply_supported": driver_item.apply_supported,
                "supported_capabilities": driver_item.supported_capabilities,
                "unsupported_reason": driver_item.unsupported_reason,
                "warnings": sorted(set([*data.get("warnings", []), *driver_item.warnings])),
            }
        )
        credential = self._credential_metadata(data.get("credential_name"))
        data["credential"] = credential.model_dump()
        data["credential_assignment_status"] = credential.status
        if credential.status == "missing" and data.get("credential_name"):
            data["warnings"] = sorted(
                {
                    *data.get("warnings", []),
                    f"Credential {data['credential_name']!r} not found",
                }
            )
        hostname = data.get("hostname")
        existing_by_hostname = self.devices.find_by_hostname(str(hostname)) if hostname else None
        existing_by_ip = self.devices.find_by_management_ip(str(data["management_ip"]))
        if existing_by_hostname is not None and (existing_by_ip is None or existing_by_hostname.id != existing_by_ip.id):
            self.imports.mark_row_invalid(row.id, "hostname already exists with a different management_ip", data)
            return
        if strict and credential.status == "missing":
            self.imports.mark_row_invalid(row.id, "Credential not found", data)
            return
        if dry_run:
            self.imports.mark_row_valid(row.id, data)
            return

        row.normalized_data = data
        self.session.flush()
        device, created = self.devices.upsert_device(data)
        if credential.id is not None:
            self.credentials.create_assignment(credential.id, device_id=device.id, vendor=device.vendor, site=device.site)
            self.devices.update_credential_assignment_status(device.id, "assigned")
        elif data.get("credential_name"):
            self.devices.update_credential_assignment_status(device.id, "missing")
        else:
            self.devices.update_credential_assignment_status(device.id, "missing")
        if created:
            self.imports.mark_row_created(row.id, device.id)
        else:
            self.imports.mark_row_updated(row.id, device.id)

    def _build_validation_item(self, row: InventoryImportRow) -> InventoryValidationItem:
        driver_item = self._build_driver_item(row)
        normalized = row.normalized_data or {}
        credential_payload = normalized.get("credential")
        credential = (
            CredentialSafeMetadata(**credential_payload)
            if isinstance(credential_payload, dict)
            else self._credential_metadata(normalized.get("credential_name"))
        )
        return InventoryValidationItem(
            **driver_item.model_dump(),
            credential=credential,
            row_status=row.status,
            error_message=row.error_message,
        )

    def _build_driver_item(self, row: InventoryImportRow) -> DriverResolutionItem:
        normalized = row.normalized_data or normalize_inventory_record(row.raw_data).data
        device_id = str(row.device_id) if row.device_id else None
        return self._resolve_driver(normalized, row_id=str(row.id), device_id=device_id)

    def _resolve_driver(self, data: dict[str, Any], row_id: str | None, device_id: str | None) -> DriverResolutionItem:
        device_input = DeviceInput(
            hostname=data.get("hostname"),
            ip_address=str(data.get("management_ip") or data.get("ip_address") or "0.0.0.0"),
            vendor=str(data.get("normalized_vendor") or data.get("vendor") or ""),
            model=str(data.get("normalized_model") or data.get("model") or ""),
            site=data.get("site"),
            role=data.get("role"),
            tags={"labels": data.get("tags", [])},
        )
        match = self.resolver.resolve(device_input)
        driver = match.driver_class(device_input.ip_address)
        capabilities = driver.detect_capabilities()
        status = "resolved"
        warnings = list(data.get("warnings", []))
        unsupported_reason: str | None = None
        if match.driver_class in {GenericSSHDriver, ReadOnlyICMPDriver}:
            status = "unsupported"
            unsupported_reason = match.reason
            warnings.append(match.reason)
        elif not capabilities.destructive_apply_confirmed:
            warnings.append("Driver template is not confirmed for destructive apply")
        return DriverResolutionItem(
            row_id=row_id,
            device_id=device_id,
            hostname=data.get("hostname"),
            management_ip=data.get("management_ip") or data.get("ip_address"),
            vendor=str(data.get("vendor") or ""),
            model=str(data.get("model") or ""),
            normalized_vendor=str(data.get("normalized_vendor") or data.get("vendor") or ""),
            normalized_model=str(data.get("normalized_model") or data.get("model") or ""),
            driver_name=driver.name,
            driver_resolution_status=status,
            apply_supported=capabilities.destructive_apply_confirmed,
            supported_capabilities=supported_capabilities(capabilities),
            unsupported_reason=unsupported_reason,
            warnings=sorted(set(warnings)),
        )

    def _capabilities_for_item(self, item: DriverResolutionItem) -> dict[str, Any]:
        device_input = DeviceInput(
            ip_address=item.management_ip or "0.0.0.0",
            vendor=item.normalized_vendor,
            model=item.normalized_model,
        )
        return asdict(self.resolver.resolve(device_input).driver_class(device_input.ip_address).detect_capabilities())

    def _credential_metadata(self, credential_name: Any) -> CredentialSafeMetadata:
        if not credential_name:
            return CredentialSafeMetadata(status="missing")
        credential = self.credentials.get_by_name(str(credential_name))
        if credential is None:
            return CredentialSafeMetadata(name=str(credential_name), status="missing")
        return CredentialSafeMetadata(id=str(credential.id), name=credential.name, username=credential.username, status="assigned")


def supported_capabilities(capabilities: Any) -> list[str]:
    result: list[str] = []
    for field_name, label in (
        ("supports_ssh", "ssh"),
        ("supports_telnet", "telnet"),
        ("supports_snmp", "snmp"),
        ("supports_vlan", "vlan"),
        ("supports_acl", "acl"),
        ("supports_trunk", "trunk"),
        ("supports_password_change", "password_change"),
        ("supports_interface_description", "interface_description"),
        ("supports_lldp", "lldp"),
        ("supports_cdp", "cdp"),
        ("supports_stp", "stp"),
    ):
        if getattr(capabilities, field_name):
            result.append(label)
    return result


def read_batch(batch: InventoryImportBatch) -> InventoryImportBatchRead:
    return InventoryImportBatchRead(
        id=str(batch.id),
        filename=batch.filename,
        source_type=batch.source_type,
        status=batch.status,
        requested_by=batch.requested_by,
        total_rows=batch.total_rows,
        valid_rows=batch.valid_rows,
        invalid_rows=batch.invalid_rows,
        created_devices=batch.created_devices,
        updated_devices=batch.updated_devices,
        skipped_rows=batch.skipped_rows,
        error_summary=batch.error_summary,
        created_at=batch.created_at.isoformat(),
        finished_at=batch.finished_at.isoformat() if batch.finished_at else None,
    )


def read_row(row: InventoryImportRow) -> InventoryImportRowRead:
    return InventoryImportRowRead(
        id=str(row.id),
        batch_id=str(row.batch_id),
        row_index=row.row_index,
        raw_data=row.raw_data,
        normalized_data=row.normalized_data,
        status=row.status,
        error_message=row.error_message,
        device_id=str(row.device_id) if row.device_id else None,
        created_at=row.created_at.isoformat(),
    )


def read_inventory_device(device: Device) -> InventoryDeviceRead:
    management_ip = str(device.management_ip or device.ip_address)
    return InventoryDeviceRead(
        id=str(device.id),
        hostname=device.hostname,
        management_ip=management_ip,
        ip_address=str(device.ip_address),
        vendor=device.vendor,
        model=device.model,
        normalized_vendor=device.normalized_vendor,
        normalized_model=device.normalized_model,
        platform=device.platform,
        site=device.site,
        location=device.location,
        rack=device.rack,
        role=device.role,
        tags=tag_labels(device.tags),
        driver_name=device.driver_name,
        driver_resolution_status=device.driver_resolution_status,
        credential_assignment_status=device.credential_assignment_status,
        discovery_status=device.discovery_status,
        discovery_error=device.discovery_error,
        discovery_last_checked_at=device.discovery_last_checked_at.isoformat() if device.discovery_last_checked_at else None,
        last_seen_at=device.last_seen_at.isoformat() if device.last_seen_at else None,
        serial_number=device.serial_number,
        os_version=device.os_version,
        capabilities=device.capabilities,
    )
