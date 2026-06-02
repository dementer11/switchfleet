from app.db.session import SessionLocal
from app.services.lab_apply_service import LabApplyService
from app.services.real_lab_apply_runner import RealLabApplyResult, RealLabApplyRunner
from app.services.transport_runtime import RuntimeCredentials
from app.services.apply_safety_kernel import ApplySafetyEvaluation
from tests.enterprise.lab_apply_helpers import allowed_lab_payload, create_lab_device, execute_permissions, lab_settings


class FakeRealRunner(RealLabApplyRunner):
    def execute(
        self,
        evaluation: ApplySafetyEvaluation,
        credentials: RuntimeCredentials,
        *,
        port: int = 22,
        timeout: int = 60,
    ) -> RealLabApplyResult:
        assert evaluation.decision.allowed is True
        assert credentials.password == "VaultSecret"
        assert evaluation.transport_decision is not None
        return RealLabApplyResult(
            executed=True,
            transport_kind=evaluation.transport_decision.selected_transport.value,
            command_count=1,
            commands=evaluation.decision.safe_command_plan[:1],
        )


def test_lab_apply_service_real_path_decrypts_only_after_allowed() -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    payload = allowed_lab_payload(session, device)
    payload.use_fake_transport = False

    response = LabApplyService(session, settings=lab_settings(device), real_runner=FakeRealRunner()).execute(
        payload,
        actor="netadmin",
        actor_permissions=execute_permissions(),
    )

    assert response.executed is True
    assert response.fake_transport is False


class SecretLeakingFailureRunner(RealLabApplyRunner):
    def execute(
        self,
        evaluation: ApplySafetyEvaluation,
        credentials: RuntimeCredentials,
        *,
        port: int = 22,
        timeout: int = 60,
    ) -> RealLabApplyResult:
        raise RuntimeError(f"auth failed for {credentials.password}")


def test_lab_apply_service_real_path_returns_redacted_failure() -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    payload = allowed_lab_payload(session, device)
    payload.use_fake_transport = False

    response = LabApplyService(session, settings=lab_settings(device), real_runner=SecretLeakingFailureRunner()).execute(
        payload,
        actor="netadmin",
        actor_permissions=execute_permissions(),
    )

    assert response.executed is False
    assert response.fake_transport is False
    assert "VaultSecret" not in str(response)
    assert "<redacted>" in response.audit["error"]
