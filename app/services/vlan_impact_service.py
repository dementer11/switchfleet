from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.config_backup import ConfigSnapshot
from app.db.models.device import Device
from app.db.session import SessionLocal
from app.repositories.config_snapshots import ConfigSnapshotRepository
from app.repositories.device_inventory import DeviceInventoryRepository
from app.repositories.vlan_workflows import VlanWorkflowRepository
from app.schemas.vlan_workflow import VlanChangeImpactPreview, VlanDeviceImpactRead


class VlanImpactService:
    def __init__(self, session: Session | None = None):
        self.session = session or SessionLocal()
        self.repository = VlanWorkflowRepository(self.session)
        self.devices = DeviceInventoryRepository(self.session)
        self.snapshots = ConfigSnapshotRepository(self.session)

    def build_impact_preview(self, request_id: str) -> VlanChangeImpactPreview:
        request = self.repository.get_request(request_id)
        rows = self.repository.get_request_devices(request.id)
        devices: list[VlanDeviceImpactRead] = []
        warnings: list[str] = []
        for row in rows:
            device = self.devices.get(row.device_id)
            snapshot = self.snapshots.get_latest_snapshot_for_device(device.id)
            impact = self._device_impact(device, snapshot, request.vlan_id, row.status)
            devices.append(impact)
            if snapshot is None:
                warnings.append(f"No snapshot available for device {device.id}; impact is incomplete")
            self.repository.update_device_plan(
                request.id,
                device.id,
                planned_commands=row.planned_commands,
                rollback_commands=row.rollback_commands,
                impact_summary=impact.model_dump(),
            )
        risk_level, risk_summary = self.estimate_risk(str(request.id), devices)
        self.repository.update_request_risk(request.id, risk_level, risk_summary)
        return VlanChangeImpactPreview(
            request_id=str(request.id),
            operation=request.operation,
            vlan_id=request.vlan_id,
            vlan_name=request.vlan_name,
            target_device_count=len(devices),
            ready_device_count=sum(1 for item in devices if item.status in {"validated", "ready"}),
            blocked_device_count=sum(1 for item in devices if item.status == "blocked"),
            unsupported_device_count=sum(1 for item in devices if item.status == "unsupported"),
            devices=devices,
            risk_level=risk_level,
            risk_summary=risk_summary,
            warnings=sorted(set(warnings)),
        )

    def read_impact_preview(self, request_id: str) -> VlanChangeImpactPreview:
        request = self.repository.get_request(request_id)
        rows = self.repository.get_request_devices(request.id)
        devices: list[VlanDeviceImpactRead] = []
        warnings: list[str] = []
        for row in rows:
            if row.impact_summary:
                devices.append(VlanDeviceImpactRead(**row.impact_summary))
                continue
            device = self.devices.get(row.device_id)
            snapshot = self.snapshots.get_latest_snapshot_for_device(device.id)
            devices.append(self._device_impact(device, snapshot, request.vlan_id, row.status))
            if snapshot is None:
                warnings.append(f"No snapshot available for device {device.id}; impact is incomplete")
        if request.risk_summary is None:
            risk_level, risk_summary = self.estimate_risk(str(request.id), devices)
        else:
            risk_level = request.risk_level
            risk_summary = request.risk_summary
        return VlanChangeImpactPreview(
            request_id=str(request.id),
            operation=request.operation,
            vlan_id=request.vlan_id,
            vlan_name=request.vlan_name,
            target_device_count=len(devices),
            ready_device_count=sum(1 for item in devices if item.status in {"validated", "ready"}),
            blocked_device_count=sum(1 for item in devices if item.status == "blocked"),
            unsupported_device_count=sum(1 for item in devices if item.status == "unsupported"),
            devices=devices,
            risk_level=risk_level,
            risk_summary=risk_summary,
            warnings=sorted(set(warnings)),
        )

    def estimate_risk(self, request_id: str, devices: list[VlanDeviceImpactRead] | None = None) -> tuple[str, dict[str, Any]]:
        request = self.repository.get_request(request_id)
        devices = devices if devices is not None else self.build_impact_preview(request_id).devices
        access_count = sum(len(device.access_ports_potentially_affected) for device in devices)
        trunk_count = sum(len(device.trunk_ports_potentially_affected) for device in devices)
        existing_count = sum(1 for device in devices if device.existing_vlan_detected)
        if request.operation in {"delete_vlan", "remove_access_vlan"} and access_count:
            risk_level = "critical"
        elif request.operation in {"delete_vlan", "add_trunk_vlan", "remove_trunk_vlan"}:
            risk_level = "high"
        elif request.operation == "rename_vlan":
            risk_level = "medium"
        else:
            risk_level = "low" if access_count == 0 and trunk_count == 0 else "medium"
        return risk_level, {
            "existing_vlan_device_count": existing_count,
            "access_ports_potentially_affected": access_count,
            "trunk_ports_potentially_affected": trunk_count,
        }

    def summarize_affected_devices(self, request_id: str) -> dict[str, int]:
        preview = self.build_impact_preview(request_id)
        return {
            "target_device_count": preview.target_device_count,
            "ready_device_count": preview.ready_device_count,
            "blocked_device_count": preview.blocked_device_count,
            "unsupported_device_count": preview.unsupported_device_count,
        }

    def detect_vlan_existing_state_from_snapshot(self, device_id: str, vlan_id: int) -> bool:
        snapshot = self.snapshots.get_latest_snapshot_for_device(device_id)
        if snapshot is None:
            return False
        return self._detect_existing_vlan(snapshot.config_text, vlan_id)

    def detect_interfaces_affected_from_snapshot(self, device_id: str, vlan_id: int) -> dict[str, list[str]]:
        snapshot = self.snapshots.get_latest_snapshot_for_device(device_id)
        if snapshot is None:
            return {"interfaces": [], "access_ports": [], "trunk_ports": []}
        access_ports, trunk_ports = self._detect_ports(snapshot.config_text, vlan_id)
        return {
            "interfaces": sorted(set(access_ports + trunk_ports)),
            "access_ports": access_ports,
            "trunk_ports": trunk_ports,
        }

    def build_drift_report(self, scope: str) -> dict[str, str]:
        return {"scope": scope, "status": "not_applicable_for_vlan_workflow"}

    def _device_impact(
        self,
        device: Device,
        snapshot: ConfigSnapshot | None,
        vlan_id: int,
        status: str,
    ) -> VlanDeviceImpactRead:
        existing = False
        access_ports: list[str] = []
        trunk_ports: list[str] = []
        warnings: list[str] = []
        if snapshot is not None:
            existing = self._detect_existing_vlan(snapshot.config_text, vlan_id)
            access_ports, trunk_ports = self._detect_ports(snapshot.config_text, vlan_id)
        else:
            warnings.append("No sanitized snapshot available; impact is best-effort only")
        return VlanDeviceImpactRead(
            device_id=str(device.id),
            hostname=device.hostname,
            management_ip=str(device.management_ip or device.ip_address),
            vendor=device.vendor,
            model=device.model,
            driver_name=device.driver_name,
            status=status,
            existing_vlan_detected=existing,
            interfaces_potentially_affected=sorted(set(access_ports + trunk_ports)),
            trunk_ports_potentially_affected=trunk_ports,
            access_ports_potentially_affected=access_ports,
            warnings=warnings,
            errors=[],
        )

    def _detect_existing_vlan(self, config_text: str, vlan_id: int) -> bool:
        escaped = re.escape(str(vlan_id))
        if re.search(rf"(?im)^\s*vlan\s+{escaped}\b", config_text):
            return True
        if re.search(rf"(?im)^\s*vlan\s+batch\b.*\b{escaped}\b", config_text):
            return True
        return False

    def _detect_ports(self, config_text: str, vlan_id: int) -> tuple[list[str], list[str]]:
        access_ports: list[str] = []
        trunk_ports: list[str] = []
        current_interface: str | None = None
        current_lines: list[str] = []
        for raw_line in config_text.splitlines() + ["interface __end__"]:
            line = raw_line.strip()
            if line.lower().startswith("interface "):
                if current_interface is not None:
                    self._classify_interface_block(current_interface, current_lines, vlan_id, access_ports, trunk_ports)
                current_interface = line.split(maxsplit=1)[1]
                current_lines = []
            elif current_interface is not None:
                current_lines.append(line)
        vlan_block = self._procurve_vlan_block_ports(config_text, vlan_id)
        access_ports.extend(vlan_block["access"])
        trunk_ports.extend(vlan_block["trunk"])
        return sorted(set(access_ports)), sorted(set(trunk_ports))

    def _classify_interface_block(
        self,
        interface: str,
        lines: list[str],
        vlan_id: int,
        access_ports: list[str],
        trunk_ports: list[str],
    ) -> None:
        joined = "\n".join(lines).casefold()
        vlan = str(vlan_id)
        access_tokens = (f"switchport access vlan {vlan}", f"port access vlan {vlan}", f"port default vlan {vlan}")
        trunk_tokens = (
            f"switchport trunk allowed vlan {vlan}",
            f"switchport trunk allowed vlan add {vlan}",
            f"port trunk allow-pass vlan {vlan}",
            f"port trunk permit vlan {vlan}",
        )
        if any(token in joined for token in access_tokens):
            access_ports.append(interface)
        if any(token in joined for token in trunk_tokens):
            trunk_ports.append(interface)

    def _procurve_vlan_block_ports(self, config_text: str, vlan_id: int) -> dict[str, list[str]]:
        access: list[str] = []
        trunk: list[str] = []
        in_vlan = False
        for raw_line in config_text.splitlines():
            line = raw_line.strip()
            if re.match(r"(?i)^vlan\s+\d+", line):
                in_vlan = line.split()[1] == str(vlan_id)
                continue
            if not in_vlan:
                continue
            lowered = line.casefold()
            if lowered.startswith("untagged "):
                access.extend(port.strip() for port in line.split(maxsplit=1)[1].split(","))
            if lowered.startswith("tagged "):
                trunk.extend(port.strip() for port in line.split(maxsplit=1)[1].split(","))
            if lowered == "exit":
                in_vlan = False
        return {"access": sorted(set(access)), "trunk": sorted(set(trunk))}
