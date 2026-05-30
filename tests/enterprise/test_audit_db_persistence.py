from __future__ import annotations

from datetime import timedelta

from app.db.session import SessionLocal
from app.services.audit_service import AuditService
from app.services.runtime_state import utcnow


def test_audit_events_are_sanitized_before_database_write_and_filters_work() -> None:
    service = AuditService(SessionLocal())
    event = service.write(
        actor="alice",
        action="credential.created",
        object_type="credential",
        object_id="cred-1",
        before={"password": "BeforeSecret"},
        after={"command": "username admin secret CommandSecret"},
        metadata={"token": "TokenSecret"},
    )

    stored = service.repository.list(actor="alice")[0]
    rendered = str(stored.before) + str(stored.after) + str(stored.extra_metadata)
    assert "BeforeSecret" not in rendered
    assert "CommandSecret" not in rendered
    assert "TokenSecret" not in rendered
    assert stored.before == {"password": "<redacted>"}
    assert stored.after == {"command": "username admin secret <redacted>"}
    assert stored.extra_metadata == {"token": "<redacted>"}
    assert service.list(actor="alice")[0].id == event.id
    assert service.list(action="credential.created")[0].id == event.id
    assert service.list(object_type="credential")[0].id == event.id
    assert service.list(date_from=utcnow() + timedelta(days=1)) == []
