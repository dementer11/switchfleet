from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.config_backup import ConfigRestorePlan
from app.repositories import coerce_uuid


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ConfigRestorePlanRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_restore_plan(
        self,
        device_id: str | uuid.UUID,
        target_snapshot_id: str | uuid.UUID,
        requested_by: str,
        plan_text: str,
        risk_level: str,
        warnings: list[str] | None = None,
        status: str = "pending_approval",
    ) -> ConfigRestorePlan:
        plan = ConfigRestorePlan(
            device_id=coerce_uuid(device_id, object_name="Device"),
            target_snapshot_id=coerce_uuid(target_snapshot_id, object_name="Config snapshot"),
            status=status,
            requested_by=requested_by,
            plan_text=plan_text,
            risk_level=risk_level,
            warnings=warnings or [],
        )
        self.session.add(plan)
        self.session.flush()
        return plan

    def get_restore_plan(self, plan_id: str | uuid.UUID) -> ConfigRestorePlan:
        parsed_id = coerce_uuid(plan_id, object_name="Config restore plan")
        plan = self.session.get(ConfigRestorePlan, parsed_id)
        if plan is None:
            raise NotFoundError(f"Config restore plan {plan_id} not found")
        return plan

    def list_restore_plans(self, status: str | None = None) -> list[ConfigRestorePlan]:
        statement = select(ConfigRestorePlan)
        if status is not None:
            statement = statement.where(ConfigRestorePlan.status == status)
        return list(self.session.scalars(statement.order_by(ConfigRestorePlan.created_at.desc())).all())

    def approve_restore_plan(self, plan_id: str | uuid.UUID, approved_by: str) -> ConfigRestorePlan:
        plan = self.get_restore_plan(plan_id)
        plan.status = "approved"
        plan.approved_by = approved_by
        plan.approved_at = utcnow()
        self.session.flush()
        return plan

    def reject_restore_plan(self, plan_id: str | uuid.UUID) -> ConfigRestorePlan:
        plan = self.get_restore_plan(plan_id)
        plan.status = "rejected"
        self.session.flush()
        return plan

    def expire_restore_plan(self, plan_id: str | uuid.UUID) -> ConfigRestorePlan:
        plan = self.get_restore_plan(plan_id)
        plan.status = "expired"
        self.session.flush()
        return plan
