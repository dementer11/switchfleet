from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.repositories.credentials import CredentialRepository
from app.services.audit_service import AuditService


HEADERS = {"X-Actor": "sec", "X-Roles": "security_admin"}


def test_credentials_are_persisted_encrypted_and_never_returned() -> None:
    client = TestClient(app)

    created = client.post(
        "/api/v1/credentials",
        headers=HEADERS,
        json={"name": "core", "username": "admin", "password": "PlainSecret", "enable_password": "EnableSecret"},
    )

    assert created.status_code == 201
    credential_id = created.json()["id"]
    stored = CredentialRepository(SessionLocal()).get(credential_id)
    assert stored.encrypted_password != "PlainSecret"
    assert stored.encrypted_enable_password is not None
    assert stored.encrypted_enable_password != "EnableSecret"
    assert "PlainSecret" not in created.text
    assert "EnableSecret" not in created.text

    listed = client.get("/api/v1/credentials", headers=HEADERS)
    fetched = client.get(f"/api/v1/credentials/{credential_id}", headers=HEADERS)
    assert "password" not in listed.json()[0]
    assert "password" not in fetched.json()
    assert "PlainSecret" not in listed.text + fetched.text

    deleted = client.delete(f"/api/v1/credentials/{credential_id}", headers=HEADERS)
    assert deleted.status_code == 204
    actions = [event.action for event in AuditService().list()]
    assert "credential.created" in actions
    assert "credential.deleted" in actions
