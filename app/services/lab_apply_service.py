from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.rbac import Permission
from app.db.session import SessionLocal
from app.schemas.lab_apply import ApplySafetyDecisionRead, LabApplyEvaluateRequest, LabApplyExecutionResponse
from app.services.apply_safety_kernel import ApplySafetyKernel
from app.services.audit_service import AuditService
from app.services.lab_transport_factory import LabTransportFactory


class LabApplyService:
    def __init__(
        self,
        session: Session | None = None,
        settings: Settings | None = None,
        kernel: ApplySafetyKernel | None = None,
        transport_factory: LabTransportFactory | None = None,
        audit: AuditService | None = None,
    ):
        self.session = session or SessionLocal()
        self.settings = settings or get_settings()
        self.kernel = kernel or ApplySafetyKernel(self.session, settings=self.settings)
        self.transport_factory = transport_factory or LabTransportFactory()
        self.audit = audit or AuditService(self.session)

    def evaluate(
        self,
        payload: LabApplyEvaluateRequest,
        *,
        actor: str,
        actor_permissions: set[str] | frozenset[Permission | str],
    ) -> ApplySafetyDecisionRead:
        return self.kernel.evaluate(payload, actor_permissions=actor_permissions).decision

    def execute(
        self,
        payload: LabApplyEvaluateRequest,
        *,
        actor: str,
        actor_permissions: set[str] | frozenset[Permission | str],
    ) -> LabApplyExecutionResponse:
        evaluation = self.kernel.evaluate(payload, actor_permissions=actor_permissions)
        decision = evaluation.decision
        if not decision.allowed:
            return LabApplyExecutionResponse(
                decision=decision,
                executed=False,
                fake_transport=payload.use_fake_transport,
                transport_kind=decision.selected_transport,
                command_count=0,
                executed_commands=[],
                audit={"result": "denied", "reasons": decision.reasons},
            )
        if not payload.use_fake_transport:
            adapter = self.transport_factory.create_runtime_adapter(evaluation)
            return LabApplyExecutionResponse(
                decision=decision,
                executed=False,
                fake_transport=False,
                transport_kind=decision.selected_transport,
                command_count=0,
                executed_commands=[],
                audit={
                    "result": "runtime_adapter_ready",
                    "adapter": repr(adapter),
                    "note": "Real command send remains behind lab runner integration; no command was sent by this API response.",
                },
            )
        transport = self.transport_factory.create_fake_transport(evaluation)
        executed_commands = transport.execute(evaluation.internal_commands)
        transport.close()
        self.audit.write(
            actor=actor,
            action="lab_apply.fake_execute",
            object_type="device",
            object_id=payload.device_id,
            metadata={
                "operation": payload.operation.value,
                "fake_transport": True,
                "transport_kind": transport.transport_kind,
                "command_count": len(executed_commands),
                "commands": [command.model_dump() for command in executed_commands],
            },
        )
        return LabApplyExecutionResponse(
            decision=decision,
            executed=True,
            fake_transport=True,
            transport_kind=transport.transport_kind,
            command_count=len(executed_commands),
            executed_commands=executed_commands,
            audit=self._safe_audit_payload(payload, executed_commands),
        )

    def _safe_audit_payload(self, payload: LabApplyEvaluateRequest, commands: list[Any]) -> dict[str, Any]:
        return {
            "result": "fake_success",
            "operation": payload.operation.value,
            "device_id": payload.device_id,
            "command_count": len(commands),
            "commands": [command.model_dump() for command in commands],
        }

