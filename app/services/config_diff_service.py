from __future__ import annotations

import difflib
import hashlib
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.config_backup import ConfigSnapshot, ConfigSnapshotDiff
from app.db.models.device import Device
from app.db.session import SessionLocal
from app.repositories.config_snapshots import ConfigSnapshotRepository
from app.repositories.device_inventory import DeviceInventoryRepository
from app.schemas.config_backup import DeviceDriftRead, DriftReportResponse


class ConfigDiffService:
    def __init__(self, session: Session | None = None):
        self.session = session or SessionLocal()
        self.snapshots = ConfigSnapshotRepository(self.session)
        self.devices = DeviceInventoryRepository(self.session)

    def normalize_config_for_diff(self, config_text: str) -> str:
        lines = [line.rstrip() for line in config_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        return "\n".join(lines).strip() + "\n"

    def build_unified_diff(self, old_config: str, new_config: str) -> str:
        old_lines = self.normalize_config_for_diff(old_config).splitlines(keepends=True)
        new_lines = self.normalize_config_for_diff(new_config).splitlines(keepends=True)
        return "".join(difflib.unified_diff(old_lines, new_lines, fromfile="from_snapshot", tofile="to_snapshot"))

    def summarize_config_changes(self, diff_text: str) -> dict[str, int]:
        summary = {
            "lines_added": 0,
            "lines_removed": 0,
            "secret_lines_redacted": 0,
            "interfaces_changed": 0,
            "vlans_changed": 0,
            "acl_lines_changed": 0,
            "routing_lines_changed": 0,
            "management_lines_changed": 0,
        }
        for line in diff_text.splitlines():
            if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
                continue
            if line.startswith("+"):
                summary["lines_added"] += 1
            elif line.startswith("-"):
                summary["lines_removed"] += 1
            else:
                continue
            lowered = line.casefold()
            if "<redacted>" in lowered:
                summary["secret_lines_redacted"] += 1
            if any(token in lowered for token in ("interface ", "description", "switchport", "port link", "port trunk", "port default")):
                summary["interfaces_changed"] += 1
            if "vlan" in lowered:
                summary["vlans_changed"] += 1
            if "acl" in lowered or "access-list" in lowered or "traffic-filter" in lowered:
                summary["acl_lines_changed"] += 1
            if any(token in lowered for token in (" ip route", "router ", "ospf", "bgp", "isis", "static-route")):
                summary["routing_lines_changed"] += 1
            if any(token in lowered for token in ("aaa", "snmp", "ntp", "ssh", "local-user", "username", "management", "ip address")):
                summary["management_lines_changed"] += 1
        return summary

    def create_diff_if_changed(self, previous: ConfigSnapshot | None, current: ConfigSnapshot) -> ConfigSnapshotDiff | None:
        if previous is None or previous.config_hash == current.config_hash:
            return None
        diff_text = self.build_unified_diff(previous.config_text, current.config_text)
        diff_hash = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()
        return self.snapshots.create_diff(
            device_id=current.device_id,
            from_snapshot_id=previous.id,
            to_snapshot_id=current.id,
            diff_text=diff_text,
            diff_hash=diff_hash,
            change_summary=self.summarize_config_changes(diff_text),
        )

    def detect_drift(self, device_id: str) -> DeviceDriftRead:
        snapshots = self.snapshots.list_snapshots_for_device(device_id)
        latest = snapshots[0] if snapshots else None
        previous = snapshots[1] if len(snapshots) > 1 else None
        if latest is None:
            return DeviceDriftRead(
                device_id=device_id,
                latest_snapshot_id=None,
                previous_snapshot_id=None,
                drift_detected=False,
            )
        if previous is None or previous.config_hash == latest.config_hash:
            return DeviceDriftRead(
                device_id=device_id,
                latest_snapshot_id=str(latest.id),
                previous_snapshot_id=str(previous.id) if previous else None,
                drift_detected=False,
            )
        diff = self.snapshots.find_diff_between_snapshots(previous.id, latest.id)
        if diff is None:
            diff_text = self.build_unified_diff(previous.config_text, latest.config_text)
            return DeviceDriftRead(
                device_id=device_id,
                latest_snapshot_id=str(latest.id),
                previous_snapshot_id=str(previous.id),
                drift_detected=True,
                change_summary=self.summarize_config_changes(diff_text),
            )
        return DeviceDriftRead(
            device_id=device_id,
            latest_snapshot_id=str(latest.id),
            previous_snapshot_id=str(previous.id),
            drift_detected=True,
            diff_id=str(diff.id) if diff else None,
            change_summary=diff.change_summary if diff and diff.change_summary else {},
        )

    def build_drift_report(self, scope_type: str, scope_filter: dict[str, Any] | None = None) -> DriftReportResponse:
        devices = self._devices_for_scope(scope_type, scope_filter or {})
        results = [self.detect_drift(str(device.id)) for device in devices]
        return DriftReportResponse(
            scope_type=scope_type,
            device_count=len(results),
            drifted_devices=sum(1 for result in results if result.drift_detected),
            devices=results,
        )

    def _devices_for_scope(self, scope_type: str, scope_filter: dict[str, Any]) -> list[Device]:
        if scope_type == "all":
            return self.devices.list_devices()
        if scope_type == "site":
            return self.devices.list_by_site(str(scope_filter.get("site") or ""))
        if scope_type == "tag":
            return self.devices.list_by_tag(str(scope_filter.get("tag") or ""))
        if scope_type == "device_ids":
            return [self.devices.get(device_id) for device_id in scope_filter.get("device_ids", [])]
        if scope_type == "query":
            devices = self.devices.list_devices()
            for field in ("vendor", "model", "driver_name", "status", "role"):
                value = scope_filter.get(field)
                if value:
                    devices = [device for device in devices if str(getattr(device, field, "")) == str(value)]
            return devices
        return []
