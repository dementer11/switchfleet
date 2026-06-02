from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.rbac import Permission
from app.db.session import SessionLocal
from app.schemas.lab_apply import ApplySafetyDecisionRead, LabApplyEvaluateRequest, LabApplyExecutionResponse
from app.services.apply_safety_kernel import ApplySafetyKernel
from app.services.audit_service import AuditService
from app.services.credential_vault_service import CredentialVaultService
from app.services.lab_transport_factory import LabTransportFactory
from app.services.real_lab_apply_runner import RealLabApplyRunner
from app.services.transport_runtime import RuntimeCredentials
from app.utils.masking import mask_secrets


class LabApplyService:
    def __init__(
        self,
        session: Session | None = None,
        settings: Settings | None = None,
        kernel: ApplySafetyKernel | None = None,
        transport_factory: LabTransportFactory | None = None,
        real_runner: RealLabApplyRunner | None = None,
        audit: AuditService | None = None,
    ):
        self.session = session or SessionLocal()
        self.settings = settings or get_settings()
        self.kernel = kernel or ApplySafetyKernel(self.session, settings=self.settings)
        self.transport_factory = transport_factory or LabTransportFactory()
        self.real_runner = real_runner or RealLabApplyRunner()
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
            secret: str | None = None
            vault = CredentialVaultService(self.session, settings=self.settings)
            try:
                metadata = vault.get_metadata(payload.credential_ref or "")
                secret = vault.decrypt_for_execution_after_safety(payload.credential_ref or "")
                result = self.real_runner.execute(
                    evaluation,
                    RuntimeCredentials(username=metadata.username, password=secret),
                )
            except Exception as exc:
                safe_error = mask_secrets(str(exc), explicit_secrets=[secret] if secret else [])
                self.audit.write(
                    actor=actor,
                    action="lab_apply.real_execute_failed",
                    object_type="device",
                    object_id=payload.device_id,
                    metadata={
                        "operation": payload.operation.value,
                        "transport_kind": decision.selected_transport,
                        "error": safe_error,
                    },
                )
                return LabApplyExecutionResponse(
                    decision=decision,
                    executed=False,
                    fake_transport=False,
                    transport_kind=decision.selected_transport,
                    command_count=0,
                    executed_commands=[],
                    audit={"result": "failed", "error": safe_error},
                )
            self.audit.write(
                actor=actor,
                action="lab_apply.real_execute",
                object_type="device",
                object_id=payload.device_id,
                metadata={
                    "operation": payload.operation.value,
                    "transport_kind": result.transport_kind,
                    "command_count": result.command_count,
                    "failed": result.failed,
                    "error": result.error,
                    "outputs": [output.__dict__ for output in result.outputs],
                },
            )
            return LabApplyExecutionResponse(
                decision=decision,
                executed=result.executed,
                fake_transport=False,
                transport_kind=result.transport_kind,
                command_count=result.command_count,
                executed_commands=result.commands,
                audit={
                    "result": "success" if result.executed else "failed",
                    "outputs": [output.__dict__ for output in result.outputs],
                    "error": result.error,
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

