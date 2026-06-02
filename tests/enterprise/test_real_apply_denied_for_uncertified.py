from app.core.config import Settings
from app.core.vendor_driver_contracts import ExecutionMode, VendorOperation
from app.db.session import SessionLocal
from app.schemas.lab_apply import LabApplyEvaluateRequest
from app.services.apply_safety_kernel import ApplySafetyKernel
from tests.enterprise.lab_apply_helpers import allowed_lab_payload, create_lab_device, execute_permissions, lab_settings


def test_production_apply_denied_even_when_lab_gates_are_satisfied() -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    payload = allowed_lab_payload(session, device)
    payload.execution_mode = ExecutionMode.production_apply

    decision = ApplySafetyKernel(session, settings=lab_settings(device)).evaluate(
        payload,
        actor_permissions=execute_permissions(),
    ).decision

    assert decision.allowed is False
    assert decision.production_allowed is False
    assert "production_apply is denied" in " ".join(decision.reasons)


def test_lab_apply_denied_when_real_apply_or_lab_flag_disabled() -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    payload = allowed_lab_payload(session, device)

    for settings in (
        Settings(environment="test", secret_key="unit-test-secret-key-for-vault", allow_real_device_apply=False, lab_real_apply_enabled=True),
        Settings(environment="test", secret_key="unit-test-secret-key-for-vault", allow_real_device_apply=True, lab_real_apply_enabled=False),
    ):
        decision = ApplySafetyKernel(session, settings=settings).evaluate(payload, actor_permissions=execute_permissions()).decision
        assert decision.allowed is False
        assert "environment_flags" in decision.denied_gates


def test_uncertified_eltex_bulat_generic_icmp_unknown_are_denied() -> None:
    session = SessionLocal()
    devices = [
        create_lab_device(session, vendor="Eltex", model="MES2324", driver_name="EltexMESDriver"),
        create_lab_device(session, vendor="Bulat", model="BS2500", driver_name="BulatBSDriver"),
        create_lab_device(session, vendor="Generic", model="GenericSSH", driver_name="GenericSSHDriver"),
        create_lab_device(session, vendor="ICMP", model="icmp-only", driver_name="ReadOnlyICMPDriver"),
        create_lab_device(session, vendor="Huawei", model="Unknown Product", driver_name=""),
    ]

    for device in devices:
        payload = LabApplyEvaluateRequest(device_id=str(device.id), operation=VendorOperation.vlan_create)
        decision = ApplySafetyKernel(session, settings=lab_settings(device)).evaluate(
            payload,
            actor_permissions=execute_permissions(),
        ).decision
        assert decision.allowed is False
