from app.core.config import Settings
from app.core.rbac import Permission
from app.core.vendor_driver_contracts import ExecutionMode, VendorOperation
from app.db.session import SessionLocal
from app.schemas.lab_apply import LabApplyEvaluateRequest
from app.services.apply_safety_kernel import ApplySafetyKernel
from tests.enterprise.lab_apply_helpers import allowed_lab_payload, create_lab_device, execute_permissions, lab_settings


def test_apply_safety_kernel_denies_missing_gates_by_default() -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    payload = LabApplyEvaluateRequest(device_id=str(device.id), operation=VendorOperation.password_change)

    evaluation = ApplySafetyKernel(session, settings=Settings(environment="test")).evaluate(
        payload,
        actor_permissions=set(),
    )

    assert evaluation.decision.allowed is False
    assert "environment_flags" in evaluation.decision.denied_gates
    assert "credential_reference" in evaluation.decision.denied_gates
    assert "actor_permission" in evaluation.decision.denied_gates


def test_apply_safety_kernel_allows_only_lab_apply_with_all_gates() -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    payload = allowed_lab_payload(session, device)

    evaluation = ApplySafetyKernel(session, settings=lab_settings(device)).evaluate(
        payload,
        actor_permissions=execute_permissions(),
    )

    assert evaluation.decision.allowed is True
    assert evaluation.decision.production_allowed is False
    assert evaluation.decision.command_hash == payload.simulation_hash
    assert "VerySecret" not in str(evaluation.decision.safe_command_plan)


def test_apply_safety_kernel_requires_credential_use_permission(monkeypatch) -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    payload = allowed_lab_payload(session, device)

    def fail_if_secret_metadata_is_checked(*args, **kwargs):
        raise AssertionError("credential metadata was checked before use_credential_secrets permission")

    monkeypatch.setattr("app.services.apply_safety_kernel.CredentialVaultService.check_usable", fail_if_secret_metadata_is_checked)
    evaluation = ApplySafetyKernel(session, settings=lab_settings(device)).evaluate(
        payload,
        actor_permissions={Permission.execute_lab_apply.value},
    )

    assert evaluation.decision.allowed is False
    assert "actor_permission" in evaluation.decision.denied_gates
    assert "use_credential_secrets" in " ".join(evaluation.decision.reasons)


def test_apply_safety_kernel_denies_production_and_hash_mismatch() -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    payload = allowed_lab_payload(session, device)
    payload.execution_mode = ExecutionMode.production_apply
    payload.simulation_hash = "mismatch"

    evaluation = ApplySafetyKernel(session, settings=lab_settings(device)).evaluate(
        payload,
        actor_permissions=execute_permissions(),
    )

    assert evaluation.decision.allowed is False
    assert "execution_mode" in evaluation.decision.denied_gates
    assert "simulation_hash" in evaluation.decision.denied_gates


def test_apply_safety_kernel_denies_unknown_generic_and_icmp() -> None:
    session = SessionLocal()
    unknown = create_lab_device(session, vendor="Huawei", model="Unknown Product", driver_name="")
    generic = create_lab_device(session, vendor="Generic", model="GenericSSH", driver_name="GenericSSHDriver")
    icmp = create_lab_device(session, vendor="ICMP", model="icmp-only", driver_name="ReadOnlyICMPDriver")

    for device in (unknown, generic, icmp):
        payload = LabApplyEvaluateRequest(device_id=str(device.id), operation=VendorOperation.password_change)
        decision = ApplySafetyKernel(session, settings=lab_settings(device)).evaluate(
            payload,
            actor_permissions=execute_permissions(),
        ).decision
        assert decision.allowed is False
        assert "runtime_decision" in decision.denied_gates or "vendor_contract" in decision.denied_gates
