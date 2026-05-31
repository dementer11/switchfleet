from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.db.models.config_backup import ConfigRestorePlan, ConfigSnapshot
from app.db.session import SessionLocal
from app.repositories.config_restore_plans import ConfigRestorePlanRepository
from app.repositories.config_snapshots import ConfigSnapshotRepository
from app.repositories.device_inventory import DeviceInventoryRepository
from app.schemas.config_backup import ConfigRestorePlanRead


class ConfigRestoreService:
    def __init__(self, session: Session | None = None):
        self.session = session or SessionLocal()
        self.restore_plans = ConfigRestorePlanRepository(self.session)
        self.snapshots = ConfigSnapshotRepository(self.session)
        self.devices = DeviceInventoryRepository(self.session)

    def create_restore_plan(self, device_id: str, target_snapshot_id: str, requested_by: str) -> ConfigRestorePlanRead:
        device = self.devices.get(device_id)
        snapshot = self.snapshots.get_snapshot(target_snapshot_id)
        if snapshot.device_id != device.id:
            raise ConflictError("Target snapshot belongs to a different device")
        risk = self.assess_restore_risk(snapshot.config_text)
        warnings = [
            "Restore plan is preview-only; no device apply endpoint exists.",
            "Review sanitized snapshot text before any future manual restore.",
        ]
        if risk in {"high", "critical"}:
            warnings.append("Snapshot includes high-risk configuration areas.")
        plan = self.restore_plans.create_restore_plan(
            device_id=device.id,
            target_snapshot_id=snapshot.id,
            requested_by=requested_by,
            plan_text=self.build_restore_plan_text(str(device.id), snapshot),
            risk_level=risk,
            warnings=warnings,
        )
        return read_restore_plan(plan)

    def build_restore_plan_text(self, device_id: str, snapshot: ConfigSnapshot) -> str:
        return (
            "RESTORE PREPARATION ONLY\n"
            f"Device: {device_id}\n"
            f"Target snapshot: {snapshot.id}\n"
            f"Config type: {snapshot.config_type}\n"
            f"Snapshot hash: {snapshot.config_hash}\n\n"
            "No commands will be sent by SwitchFleet for this plan. Use this preview for human review and future approved workflows.\n\n"
            "Sanitized target configuration:\n"
            f"{snapshot.config_text}"
        )

    def assess_restore_risk(self, config_text: str) -> str:
        lowered = config_text.casefold()
        if any(token in lowered for token in ("aaa", "authentication", "authorization", "snmp-server community", "local-user", "username", "boot", "firmware", "management ip")):
            return "critical"
        if any(token in lowered for token in ("acl", "access-list", "traffic-filter", " ip route", "router ", "ospf", "bgp", "vlan batch", "port trunk", "port default vlan", "switchport access")):
            return "high"
        if any(token in lowered for token in ("description", "name ", "vlan ")):
            return "medium"
        return "low"

    def approve_restore_plan(self, plan_id: str, approved_by: str) -> ConfigRestorePlanRead:
        return read_restore_plan(self.restore_plans.approve_restore_plan(plan_id, approved_by))

    def reject_restore_plan(self, plan_id: str) -> ConfigRestorePlanRead:
        return read_restore_plan(self.restore_plans.reject_restore_plan(plan_id))

    def get_restore_plan(self, plan_id: str) -> ConfigRestorePlanRead:
        return read_restore_plan(self.restore_plans.get_restore_plan(plan_id))

    def list_restore_plans(self, status: str | None = None) -> list[ConfigRestorePlanRead]:
        return [read_restore_plan(plan) for plan in self.restore_plans.list_restore_plans(status=status)]


def read_restore_plan(plan: ConfigRestorePlan) -> ConfigRestorePlanRead:
    return ConfigRestorePlanRead(
        id=str(plan.id),
        device_id=str(plan.device_id),
        target_snapshot_id=str(plan.target_snapshot_id),
        status=plan.status,
        requested_by=plan.requested_by,
        plan_text=plan.plan_text,
        risk_level=plan.risk_level,
        warnings=list(plan.warnings or []),
        created_at=plan.created_at.isoformat(),
        approved_at=plan.approved_at.isoformat() if plan.approved_at else None,
        approved_by=plan.approved_by,
    )
