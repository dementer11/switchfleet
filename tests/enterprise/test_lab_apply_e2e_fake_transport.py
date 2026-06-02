from app.db.session import SessionLocal
from app.services.lab_apply_service import LabApplyService
from tests.enterprise.lab_apply_helpers import allowed_lab_payload, create_lab_device, execute_permissions, lab_settings


def test_lab_apply_e2e_fake_transport_records_only_redacted_commands() -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    payload = allowed_lab_payload(session, device)

    result = LabApplyService(session, settings=lab_settings(device)).execute(
        payload,
        actor="netadmin",
        actor_permissions=execute_permissions(),
    )

    assert result.executed is True
    assert result.fake_transport is True
    assert result.command_count == len(payload.command_plan)
    assert "VerySecret" not in result.model_dump_json()
    assert "<redacted>" in result.model_dump_json()
