from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.device import Device
from app.repositories import coerce_uuid


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DeviceInventoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_device(self, data: dict[str, Any]) -> tuple[Device, bool]:
        management_ip = str(data.get("management_ip") or data.get("ip_address") or "").strip()
        if not management_ip:
            raise ValueError("management_ip is required")
        existing = self.find_by_management_ip(management_ip)
        created = existing is None
        device = existing or Device(
            ip_address=management_ip,
            management_ip=management_ip,
            vendor=str(data.get("vendor") or ""),
            model=str(data.get("model") or ""),
            status="known",
        )
        self._apply_metadata(device, data)
        if created:
            self.session.add(device)
        self.session.flush()
        return device, created

    def find_by_management_ip(self, management_ip: str) -> Device | None:
        return self.session.scalar(
            select(Device).where((Device.management_ip == management_ip) | (Device.ip_address == management_ip))
        )

    def find_by_hostname(self, hostname: str) -> Device | None:
        return self.session.scalar(select(Device).where(Device.hostname == hostname))

    def find_duplicates(self, management_ip: str | None = None, hostname: str | None = None) -> list[Device]:
        seen: dict[uuid.UUID, Device] = {}
        if management_ip:
            for device in self.session.scalars(
                select(Device).where((Device.management_ip == management_ip) | (Device.ip_address == management_ip))
            ):
                seen[device.id] = device
        if hostname:
            for device in self.session.scalars(select(Device).where(Device.hostname == hostname)):
                seen[device.id] = device
        return list(seen.values())

    def list_devices(self) -> list[Device]:
        return list(self.session.scalars(select(Device).order_by(Device.site, Device.hostname, Device.ip_address)).all())

    def get(self, device_id: str | uuid.UUID) -> Device:
        parsed_id = coerce_uuid(device_id, object_name="Device")
        device = self.session.get(Device, parsed_id)
        if device is None:
            raise NotFoundError(f"Device {device_id} not found")
        return device

    def list_by_site(self, site: str) -> list[Device]:
        return list(self.session.scalars(select(Device).where(Device.site == site).order_by(Device.hostname, Device.ip_address)).all())

    def list_by_tag(self, tag: str) -> list[Device]:
        return [device for device in self.list_devices() if tag in tag_labels(device.tags)]

    def update_discovery_status(
        self,
        device_id: str | uuid.UUID,
        status: str,
        error: str | None = None,
        facts: dict[str, Any] | None = None,
    ) -> Device:
        device = self.get(device_id)
        device.discovery_status = status
        device.discovery_error = error
        device.discovery_last_checked_at = utcnow()
        if status == "reachable":
            device.last_seen = device.discovery_last_checked_at
            device.last_seen_at = device.discovery_last_checked_at
        if facts:
            for field in ("hostname", "serial_number", "os_version", "platform"):
                value = facts.get(field)
                if value:
                    setattr(device, field, str(value))
        self.session.flush()
        return device

    def update_driver_resolution(
        self,
        device_id: str | uuid.UUID,
        driver_name: str,
        status: str,
        capabilities: dict[str, Any] | None = None,
    ) -> Device:
        device = self.get(device_id)
        device.driver_name = driver_name
        device.driver_resolution_status = status
        if capabilities is not None:
            device.capabilities = capabilities
        self.session.flush()
        return device

    def update_credential_assignment_status(self, device_id: str | uuid.UUID, status: str) -> Device:
        device = self.get(device_id)
        device.credential_assignment_status = status
        self.session.flush()
        return device

    def bulk_update_tags(self, device_ids: list[str | uuid.UUID], tags: list[str]) -> list[Device]:
        updated: list[Device] = []
        safe_tags = sorted(set(tags))
        for device_id in device_ids:
            device = self.get(device_id)
            device.tags = {"labels": safe_tags}
            updated.append(device)
        self.session.flush()
        return updated

    def patch_metadata(
        self,
        device_id: str | uuid.UUID,
        site: str | None = None,
        location: str | None = None,
        rack: str | None = None,
        role: str | None = None,
        tags: list[str] | None = None,
    ) -> Device:
        device = self.get(device_id)
        if site is not None:
            device.site = site
        if location is not None:
            device.location = location
        if rack is not None:
            device.rack = rack
        if role is not None:
            device.role = role
        if tags is not None:
            device.tags = {"labels": sorted(set(tags))}
        self.session.flush()
        return device

    def _apply_metadata(self, device: Device, data: dict[str, Any]) -> None:
        management_ip = str(data.get("management_ip") or data.get("ip_address") or device.ip_address)
        device.ip_address = management_ip
        device.management_ip = management_ip
        for field in (
            "hostname",
            "vendor",
            "model",
            "normalized_vendor",
            "normalized_model",
            "platform",
            "site",
            "location",
            "rack",
            "role",
            "driver_name",
            "driver_resolution_status",
            "credential_assignment_status",
        ):
            value = data.get(field)
            if value is not None:
                setattr(device, field, value)
        if data.get("capabilities") is not None:
            device.capabilities = data["capabilities"]
        if data.get("tags") is not None:
            labels = data["tags"] if isinstance(data["tags"], list) else tag_labels(data["tags"])
            device.tags = {"labels": sorted(set(str(item) for item in labels))}


def tag_labels(tags: Any) -> list[str]:
    if isinstance(tags, dict):
        labels = tags.get("labels", [])
        if isinstance(labels, list):
            return [str(item) for item in labels]
        return [str(labels)]
    if isinstance(tags, list):
        return [str(item) for item in tags]
    if isinstance(tags, str) and tags:
        return [tags]
    return []
