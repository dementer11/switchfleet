import pytest

from app.core.exceptions import SafetyError
from app.core.vendor_driver_contracts import VendorOperation
from app.db.session import SessionLocal
from app.schemas.lab_apply import LabApplyEvaluateRequest
from app.services.apply_safety_kernel import ApplySafetyKernel
from app.services.lab_transport_factory import LabTransportFactory
from tests.enterprise.lab_apply_helpers import allowed_lab_payload, create_lab_device, execute_permissions, lab_settings


def test_lab_transport_factory_requires_allowed_safety_decision() -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    denied = ApplySafetyKernel(session, settings=lab_settings(device)).evaluate(
        LabApplyEvaluateRequest(device_id=str(device.id), operation=VendorOperation.password_change),
        actor_permissions=execute_permissions(),
    )

    with pytest.raises(SafetyError):
        LabTransportFactory().create_fake_transport(denied)


def test_lab_transport_factory_creates_fake_after_allowed_decision() -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    payload = allowed_lab_payload(session, device)
    evaluation = ApplySafetyKernel(session, settings=lab_settings(device)).evaluate(
        payload,
        actor_permissions=execute_permissions(),
    )

    transport = LabTransportFactory().create_fake_transport(evaluation)
    executed = transport.execute(evaluation.internal_commands)

    assert transport.transport_kind == "netmiko"
    assert executed
    assert "VerySecret" not in str(executed)
