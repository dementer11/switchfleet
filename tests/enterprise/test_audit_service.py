from datetime import timedelta

from app.services.audit_service import AuditService
from app.services.runtime_state import utcnow


def test_audit_service_masks_secret_values_and_filters() -> None:
    service = AuditService()
    event = service.write(
        actor="alice",
        action="credential.created",
        object_type="credential",
        object_id="cred1",
        metadata={"password": "VerySecret", "command": "username admin secret VerySecret"},
    )

    assert event.metadata["password"] == "<redacted>"
    assert "VerySecret" not in str(event.metadata)
    assert service.list(actor="alice")[0].id == event.id
    assert service.list(date_from=utcnow() + timedelta(days=1)) == []

