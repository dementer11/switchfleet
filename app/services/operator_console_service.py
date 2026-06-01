from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.repositories.operator_console import OperatorConsoleRepository
from app.schemas.operator_console import (
    OperatorConsoleAuditEvent,
    OperatorConsoleBackupSummary,
    OperatorConsoleChangeExecutionSummary,
    OperatorConsoleDashboardResponse,
    OperatorConsoleDeviceHealth,
    OperatorConsoleHealthSummary,
    OperatorConsoleLabValidationSummary,
    OperatorConsoleOverview,
    OperatorConsolePendingApproval,
    OperatorConsoleRecentActivity,
    OperatorConsoleRiskSummary,
    OperatorConsoleSafetyPosture,
    OperatorConsoleWorkflowSummary,
)


class OperatorConsoleService:
    def __init__(self, session: Session | None = None):
        self.session = session or SessionLocal()
        self.repository = OperatorConsoleRepository(self.session)

    def get_dashboard(self, limit: int = 50) -> OperatorConsoleDashboardResponse:
        return OperatorConsoleDashboardResponse(
            health=self.get_health_summary(),
            safety=self.get_safety_posture(),
            inventory=OperatorConsoleOverview(**self.repository.get_inventory_summary()),
            backups=OperatorConsoleBackupSummary(**self.repository.get_backup_summary()),
            lab_validation=OperatorConsoleLabValidationSummary(**self.repository.get_lab_validation_summary()),
            workflows=self.get_workflow_summary(),
            pending_approvals=self.get_pending_approvals(limit=limit),
            recent_activity=self.get_recent_activity(limit=limit),
            risk_summary=self.get_risk_summary(),
            change_executions=self.get_change_execution_summary(),
        )

    def get_health_summary(self) -> OperatorConsoleHealthSummary:
        return OperatorConsoleHealthSummary(**self.repository.get_device_health_summary())

    def get_safety_posture(self) -> OperatorConsoleSafetyPosture:
        return OperatorConsoleSafetyPosture(**self.repository.get_safety_posture())

    def get_workflow_summary(self) -> dict[str, OperatorConsoleWorkflowSummary]:
        return {
            key: OperatorConsoleWorkflowSummary(**value)
            for key, value in self.repository.get_workflow_summaries().items()
        }

    def get_pending_approvals(
        self,
        limit: int = 50,
        offset: int = 0,
        workflow_type: str | None = None,
        include_resolved: bool = False,
    ) -> list[OperatorConsolePendingApproval]:
        return [
            OperatorConsolePendingApproval(**item)
            for item in self.repository.get_pending_approvals(
                limit=limit,
                offset=offset,
                workflow_type=workflow_type,
                include_resolved=include_resolved,
            )
        ]

    def get_recent_activity(
        self,
        limit: int = 50,
        offset: int = 0,
        workflow_type: str | None = None,
        include_resolved: bool = False,
    ) -> list[OperatorConsoleRecentActivity]:
        return [
            OperatorConsoleRecentActivity(**item)
            for item in self.repository.get_recent_activity(
                limit=limit,
                offset=offset,
                workflow_type=workflow_type,
                include_resolved=include_resolved,
            )
        ]

    def get_device_health(
        self,
        limit: int = 100,
        offset: int = 0,
        risk_level: str | None = None,
        device_id: str | None = None,
    ) -> list[OperatorConsoleDeviceHealth]:
        return [
            OperatorConsoleDeviceHealth(**item)
            for item in self.repository.get_device_health(
                limit=limit,
                offset=offset,
                risk_level=risk_level,
                device_id=device_id,
            )
        ]

    def get_risk_summary(self) -> OperatorConsoleRiskSummary:
        return OperatorConsoleRiskSummary(**self.repository.get_risk_summary())

    def get_change_execution_summary(self) -> OperatorConsoleChangeExecutionSummary:
        return OperatorConsoleChangeExecutionSummary(**self.repository.get_change_execution_summary())

    def get_audit_events(
        self,
        limit: int = 50,
        offset: int = 0,
        workflow_type: str | None = None,
        include_resolved: bool = False,
    ) -> list[OperatorConsoleAuditEvent]:
        return [
            OperatorConsoleAuditEvent(**item)
            for item in self.repository.get_recent_activity(
                limit=limit,
                offset=offset,
                workflow_type=workflow_type,
                include_resolved=include_resolved,
            )
        ]
