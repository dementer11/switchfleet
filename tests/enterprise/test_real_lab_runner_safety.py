from app.core.config import Settings
from app.core.rbac import Permission
from app.core.vendor_driver_contracts import VendorOperation
from app.db.session import SessionLocal
from app.schemas.lab_apply import LabApplyEvaluateRequest
from app.services.lab_apply_service import LabApplyService
from app.services.real_lab_apply_runner import RealLabApplyRunner
from tests.enterprise.lab_apply_helpers import create_lab_device, lab_settings


class FailingRealRunner(RealLabApplyRunner):
    def execute(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("real runner was called before safety gates passed")


def test_execute_denies_before_decrypt_or_transport_when_gates_missing() -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    payload = LabApplyEvaluateRequest(
        device_id=str(device.id),
        operation=VendorOperation.password_change,
        use_fake_transport=False,
    )

    response = LabApplyService(
        session,
        settings=Settings(environment="test"),
        real_runner=FailingRealRunner(),
    ).execute(
        payload,
        actor="netadmin",
        actor_permissions={Permission.execute_lab_apply.value, Permission.use_credential_secrets.value},
    )

    assert response.executed is False
    assert response.decision.allowed is False


def test_production_env_cannot_enable_production_apply() -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    settings = lab_settings(device)
    settings.production_real_apply_enabled = True
    payload = LabApplyEvaluateRequest(device_id=str(device.id), operation=VendorOperation.password_change)

    decision = LabApplyService(session, settings=settings).evaluate(
        payload,
        actor="netadmin",
        actor_permissions={Permission.execute_lab_apply.value, Permission.use_credential_secrets.value},
    )

    assert decision.allowed is False
    assert "environment_flags" in decision.denied_gates
