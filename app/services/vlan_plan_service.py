from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.db.models.device import Device
from app.db.models.vlan_workflow import VlanChangeRequest
from app.db.session import SessionLocal
from app.repositories.config_snapshots import ConfigSnapshotRepository
from app.repositories.device_inventory import DeviceInventoryRepository
from app.repositories.vlan_workflows import VlanWorkflowRepository
from app.schemas.vlan_workflow import VlanChangePlanRead, VlanChangeRollbackPlanRead
from app.services.vlan_validation_service import read_device, read_request
from app.utils.masking import mask_command_list


class VlanPlanService:
    def __init__(self, session: Session | None = None):
        self.session = session or SessionLocal()
        self.repository = VlanWorkflowRepository(self.session)
        self.devices = DeviceInventoryRepository(self.session)
        self.snapshots = ConfigSnapshotRepository(self.session)

    def build_vlan_change_plan(self, request_id: str) -> VlanChangePlanRead:
        request = self.repository.get_request(request_id)
        rows = self.repository.get_request_devices(request.id)
        for row in rows:
            self.build_device_plan(str(request.id), str(row.device_id))
        self.repository.add_audit_event(request.id, "planned", "Dry-run VLAN command plan generated")
        return self._read_plan(str(request.id))

    def build_device_plan(self, request_id: str, device_id: str) -> list[str]:
        request = self.repository.get_request(request_id)
        row = self.repository.get_request_device(request.id, device_id)
        device = self.devices.get(device_id)
        if row.status in {"blocked", "unsupported", "skipped", "failed"}:
            self.repository.update_device_plan(request.id, device.id, [], [], status=row.status)
            return []
        interface = self._interface_from_request(request)
        if request.operation in {"assign_access_vlan", "remove_access_vlan", "add_trunk_vlan", "remove_trunk_vlan"} and not interface:
            self.repository.update_device_status(
                request.id,
                device.id,
                "blocked",
                errors=[f"operation {request.operation} requires scope_filter.interface"],
            )
            return []
        commands = self.build_vendor_specific_commands(device, request.operation, request.vlan_id, request.vlan_name, interface=interface)
        rollback = self.build_device_rollback_plan(str(request.id), str(device.id))
        status = "ready" if commands and rollback else "blocked"
        self.repository.update_device_plan(request.id, device.id, commands, rollback, status=status)
        return commands

    def build_vendor_specific_commands(
        self,
        device: Device,
        operation: str,
        vlan_id: int,
        vlan_name: str | None,
        interface: str | None = None,
    ) -> list[str]:
        renderer = self._renderer_family(device)
        if renderer is None:
            return []
        commands = renderer(operation, vlan_id, vlan_name, interface)
        return mask_command_list(commands)

    def build_rollback_plan(self, request_id: str) -> VlanChangeRollbackPlanRead:
        request = self.repository.get_request(request_id)
        rows = self.repository.get_request_devices(request.id)
        warnings: list[str] = []
        for row in rows:
            device = self.devices.get(row.device_id)
            rollback = self.build_device_rollback_plan(str(request.id), str(device.id))
            if not rollback and row.status not in {"blocked", "unsupported", "skipped"}:
                warnings.append(f"No rollback commands could be generated for device {device.id}")
            self.repository.update_device_plan(
                request.id,
                device.id,
                planned_commands=row.planned_commands,
                rollback_commands=rollback,
                status=row.status,
            )
        self.repository.add_audit_event(request.id, "rollback_planned", "Dry-run VLAN rollback plan generated")
        rows = self.repository.get_request_devices(request.id)
        return VlanChangeRollbackPlanRead(
            request_id=str(request.id),
            devices=[read_device(row) for row in rows],
            rollback_ready_device_count=sum(1 for row in rows if row.rollback_commands),
            warnings=warnings,
        )

    def read_rollback_plan(self, request_id: str) -> VlanChangeRollbackPlanRead:
        request = self.repository.get_request(request_id)
        rows = self.repository.get_request_devices(request.id)
        warnings = [
            f"Rollback plan has not been generated for device {row.device_id}"
            for row in rows
            if row.status not in {"blocked", "unsupported", "skipped", "failed"} and not row.rollback_commands
        ]
        return VlanChangeRollbackPlanRead(
            request_id=str(request.id),
            devices=[read_device(row) for row in rows],
            rollback_ready_device_count=sum(1 for row in rows if row.rollback_commands),
            warnings=warnings,
        )

    def build_device_rollback_plan(self, request_id: str, device_id: str) -> list[str]:
        request = self.repository.get_request(request_id)
        device = self.devices.get(device_id)
        snapshot = self.snapshots.get_latest_snapshot_for_device(device.id)
        config_text = snapshot.config_text if snapshot is not None else ""
        interface = self._interface_from_request(request)
        previous_name = self._detect_vlan_name(config_text, request.vlan_id)
        previous_access_vlan = self._detect_access_vlan(config_text, interface) if interface else None
        if request.operation == "create_vlan":
            return self.build_vendor_specific_commands(device, "delete_vlan", request.vlan_id, None, interface=interface)
        if request.operation == "rename_vlan":
            if not previous_name:
                return []
            return self.build_vendor_specific_commands(device, "rename_vlan", request.vlan_id, previous_name, interface=interface)
        if request.operation == "delete_vlan":
            return self.build_vendor_specific_commands(device, "create_vlan", request.vlan_id, previous_name, interface=interface)
        if request.operation == "assign_access_vlan" and interface:
            if previous_access_vlan is None:
                return self.build_vendor_specific_commands(device, "remove_access_vlan", request.vlan_id, None, interface=interface)
            return self.build_vendor_specific_commands(device, "assign_access_vlan", previous_access_vlan, None, interface=interface)
        if request.operation == "remove_access_vlan" and interface:
            if previous_access_vlan is None:
                return []
            return self.build_vendor_specific_commands(device, "assign_access_vlan", previous_access_vlan, None, interface=interface)
        if request.operation == "add_trunk_vlan" and interface:
            return self.build_vendor_specific_commands(device, "remove_trunk_vlan", request.vlan_id, None, interface=interface)
        if request.operation == "remove_trunk_vlan" and interface:
            return self.build_vendor_specific_commands(device, "add_trunk_vlan", request.vlan_id, None, interface=interface)
        return []

    def _read_plan(self, request_id: str) -> VlanChangePlanRead:
        request = self.repository.get_request(request_id)
        rows = self.repository.get_request_devices(request.id)
        return VlanChangePlanRead(
            request=read_request(request),
            devices=[read_device(row) for row in rows],
            planned_device_count=sum(1 for row in rows if row.planned_commands),
            blocked_device_count=sum(1 for row in rows if row.status in {"blocked", "unsupported", "failed"}),
        )

    def _renderer_family(self, device: Device) -> Any:
        mapping: dict[str, Any] = {
            "HuaweiVRPDriver": self._huawei_commands,
            "CiscoIOSDriver": self._cisco_commands,
            "HPComwareDriver": self._comware_commands,
            "HPEProCurveDriver": self._procurve_commands,
            "DellPowerConnectDriver": self._cisco_commands,
        }
        return mapping.get(device.driver_name)

    def _interface_from_request(self, request: VlanChangeRequest) -> str | None:
        value = (request.scope_filter or {}).get("interface")
        return str(value) if value else None

    def _cisco_commands(self, operation: str, vlan_id: int, vlan_name: str | None, interface: str | None) -> list[str]:
        if operation in {"create_vlan", "rename_vlan"}:
            commands = ["configure terminal", f"vlan {vlan_id}"]
            if vlan_name:
                commands.append(f"name {vlan_name}")
            return commands + ["exit", "end"]
        if operation == "delete_vlan":
            return ["configure terminal", f"no vlan {vlan_id}", "end"]
        if interface is None:
            raise ConflictError(f"operation {operation} requires interface")
        if operation == "assign_access_vlan":
            return ["configure terminal", f"interface {interface}", "switchport mode access", f"switchport access vlan {vlan_id}", "end"]
        if operation == "remove_access_vlan":
            return ["configure terminal", f"interface {interface}", "no switchport access vlan", "end"]
        if operation == "add_trunk_vlan":
            return ["configure terminal", f"interface {interface}", f"switchport trunk allowed vlan add {vlan_id}", "end"]
        if operation == "remove_trunk_vlan":
            return ["configure terminal", f"interface {interface}", f"switchport trunk allowed vlan remove {vlan_id}", "end"]
        return []

    def _huawei_commands(self, operation: str, vlan_id: int, vlan_name: str | None, interface: str | None) -> list[str]:
        if operation in {"create_vlan", "rename_vlan"}:
            commands = ["system-view", f"vlan {vlan_id}"]
            if vlan_name:
                commands.append(f"description {vlan_name}")
            return commands + ["quit", "quit"]
        if operation == "delete_vlan":
            return ["system-view", f"undo vlan {vlan_id}", "quit"]
        if interface is None:
            raise ConflictError(f"operation {operation} requires interface")
        if operation == "assign_access_vlan":
            return ["system-view", f"interface {interface}", "port link-type access", f"port default vlan {vlan_id}", "quit", "quit"]
        if operation == "remove_access_vlan":
            return ["system-view", f"interface {interface}", "undo port default vlan", "quit", "quit"]
        if operation == "add_trunk_vlan":
            return ["system-view", f"interface {interface}", f"port trunk allow-pass vlan {vlan_id}", "quit", "quit"]
        if operation == "remove_trunk_vlan":
            return ["system-view", f"interface {interface}", f"undo port trunk allow-pass vlan {vlan_id}", "quit", "quit"]
        return []

    def _comware_commands(self, operation: str, vlan_id: int, vlan_name: str | None, interface: str | None) -> list[str]:
        if operation in {"create_vlan", "rename_vlan"}:
            commands = ["system-view", f"vlan {vlan_id}"]
            if vlan_name:
                commands.append(f"name {vlan_name}")
            return commands + ["quit", "quit"]
        if operation == "delete_vlan":
            return ["system-view", f"undo vlan {vlan_id}", "quit"]
        if interface is None:
            raise ConflictError(f"operation {operation} requires interface")
        if operation == "assign_access_vlan":
            return ["system-view", f"interface {interface}", "port link-type access", f"port access vlan {vlan_id}", "quit", "quit"]
        if operation == "remove_access_vlan":
            return ["system-view", f"interface {interface}", "undo port access vlan", "quit", "quit"]
        if operation == "add_trunk_vlan":
            return ["system-view", f"interface {interface}", f"port trunk permit vlan {vlan_id}", "quit", "quit"]
        if operation == "remove_trunk_vlan":
            return ["system-view", f"interface {interface}", f"undo port trunk permit vlan {vlan_id}", "quit", "quit"]
        return []

    def _procurve_commands(self, operation: str, vlan_id: int, vlan_name: str | None, interface: str | None) -> list[str]:
        if operation in {"create_vlan", "rename_vlan"}:
            commands = [f"vlan {vlan_id}"]
            if vlan_name:
                commands.append(f"name {vlan_name}")
            return commands + ["exit"]
        if operation == "delete_vlan":
            return [f"no vlan {vlan_id}"]
        if interface is None:
            raise ConflictError(f"operation {operation} requires interface")
        if operation == "assign_access_vlan":
            return [f"vlan {vlan_id}", f"untagged {interface}", "exit"]
        if operation == "remove_access_vlan":
            return [f"vlan {vlan_id}", f"no untagged {interface}", "exit"]
        if operation == "add_trunk_vlan":
            return [f"vlan {vlan_id}", f"tagged {interface}", "exit"]
        if operation == "remove_trunk_vlan":
            return [f"vlan {vlan_id}", f"no tagged {interface}", "exit"]
        return []

    def _detect_vlan_name(self, config_text: str, vlan_id: int) -> str | None:
        pattern = re.compile(rf"(?ims)^\s*vlan\s+{vlan_id}\b(?P<body>.*?)(?:^\s*vlan\s+\d+\b|^\s*interface\s+|\Z)")
        match = pattern.search(config_text)
        if not match:
            return None
        body = match.group("body")
        for line in body.splitlines():
            stripped = line.strip()
            lowered = stripped.casefold()
            if lowered.startswith("name ") or lowered.startswith("description "):
                return stripped.split(maxsplit=1)[1].strip().strip('"')
        return None

    def _detect_access_vlan(self, config_text: str, interface: str | None) -> int | None:
        if not interface:
            return None
        pattern = re.compile(rf"(?ims)^\s*interface\s+{re.escape(interface)}\b(?P<body>.*?)(?:^\s*interface\s+|\Z)")
        match = pattern.search(config_text)
        if not match:
            return None
        body = match.group("body")
        for vlan_pattern in (
            r"switchport\s+access\s+vlan\s+(\d+)",
            r"port\s+access\s+vlan\s+(\d+)",
            r"port\s+default\s+vlan\s+(\d+)",
        ):
            vlan_match = re.search(vlan_pattern, body, flags=re.I)
            if vlan_match:
                return int(vlan_match.group(1))
        return None
