from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.repositories.credentials import CredentialRepository
from app.main import app
from app.services.audit_service import AuditService


HEADERS = {"X-Actor": "sec", "X-Roles": "security_admin"}


def test_credentials_api_never_returns_plain_password() -> None:
    client = TestClient(app)

    created = client.post(
        "/api/v1/credentials",
        headers=HEADERS,
        json={"name": "core", "username": "admin", "password": "VerySecret", "enable_password": "EnableSecret"},
    )

    assert created.status_code == 201
    created_payload = created.json()
    assert created_payload["password"] == "<redacted>"
    assert "VerySecret" not in created.text
    credential_id = created_payload["id"]
    stored = CredentialRepository(SessionLocal()).get(credential_id)
    assert stored.encrypted_password != "VerySecret"

    listed = client.get("/api/v1/credentials", headers=HEADERS)
    assert listed.status_code == 200
    assert "password" not in listed.json()[0]
    assert "VerySecret" not in listed.text

    fetched = client.get(f"/api/v1/credentials/{credential_id}", headers=HEADERS)
    assert fetched.status_code == 200
    assert "password" not in fetched.json()


def test_delete_credential_writes_audit_event() -> None:
    client = TestClient(app)
    credential_id = client.post(
        "/api/v1/credentials",
        headers=HEADERS,
        json={"name": "edge", "username": "admin", "password": "VerySecret"},
    ).json()["id"]

    deleted = client.delete(f"/api/v1/credentials/{credential_id}", headers=HEADERS)

    assert deleted.status_code == 204
    actions = [event.action for event in AuditService().list()]
    assert "credential.deleted" in actions
