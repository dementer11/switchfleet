from app.db.session import SessionLocal
from app.services.audit_service import AuditService
from app.services.lab_apply_service import LabApplyService
from tests.enterprise.lab_apply_helpers import allowed_lab_payload, create_lab_device, execute_permissions, lab_settings


def test_lab_apply_redacts_secret_commands_from_response_and_audit() -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    payload = allowed_lab_payload(session, device)

    result = LabApplyService(session, settings=lab_settings(device)).execute(
        payload,
        actor="netadmin",
        actor_permissions=execute_permissions(),
    )
    rendered = result.model_dump_json() + str(AuditService(session).list())

    assert "VerySecret" not in rendered
    assert "VaultSecret" not in rendered
    assert "<redacted>" in rendered
