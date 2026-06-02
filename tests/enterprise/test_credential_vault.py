from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.exceptions import SecretHandlingError
from app.db.models.credential import CredentialSecret
from app.db.session import SessionLocal
from app.main import app
from app.schemas.credential_vault import CredentialSecretCreate, CredentialSecretRotate
from app.services.audit_service import AuditService
from app.services.credential_vault_service import CredentialVaultService

HEADERS = {"X-Actor": "netadmin", "X-Roles": "network_admin"}
VIEWER = {"X-Actor": "viewer", "X-Roles": "viewer"}
SECRET_KEY = "credential-vault-test-key"


def test_credential_vault_requires_secret_key_and_stores_encrypted_only() -> None:
    session = SessionLocal()
    service = CredentialVaultService(session, settings=Settings(environment="test", secret_key=SECRET_KEY))

    created = service.create_secret(
        CredentialSecretCreate(name="core", username="admin", secret="PlainSecret", metadata={"apiToken": "TOKEN"}),
        actor="netadmin",
    )
    stored = session.get(CredentialSecret, created.id)

    assert stored is not None
    assert stored.encrypted_payload != "PlainSecret"
    assert "PlainSecret" not in str(created)
    assert created.metadata["apiToken"] == "<redacted>"
    assert "PlainSecret" not in str(AuditService(session).list())

    rotated = service.rotate_secret(created.id, CredentialSecretRotate(secret="NewSecret"), actor="netadmin")
    assert rotated.version == 2
    assert "NewSecret" not in str(rotated)

    disabled = service.disable_secret(created.id, actor="netadmin")
    assert disabled.active is False
    assert service.check_usable(created.id).usable is False


def test_credential_vault_refuses_without_ncp_secret_key() -> None:
    service = CredentialVaultService(SessionLocal(), settings=Settings(environment="test", secret_key=None))

    try:
        service.create_secret(CredentialSecretCreate(name="bad", username="admin", secret="PlainSecret"), actor="netadmin")
    except SecretHandlingError as exc:
        assert "NCP_SECRET_KEY" in str(exc)
    else:
        raise AssertionError("Credential vault accepted missing NCP_SECRET_KEY")


def test_credential_vault_api_never_returns_plaintext_and_enforces_rbac(monkeypatch) -> None:
    monkeypatch.setenv("NCP_SECRET_KEY", SECRET_KEY)
    get_settings.cache_clear()
    client = TestClient(app)

    viewer = client.post("/api/v1/credential-vault/secrets", headers=VIEWER, json={"name": "x", "username": "u", "secret": "Leak"})
    created = client.post(
        "/api/v1/credential-vault/secrets",
        headers=HEADERS,
        json={"name": "core", "username": "admin", "secret": "PlainSecret", "metadata": {"privateKey": "KEY"}},
    )
    secret_id = created.json()["id"]
    listed = client.get("/api/v1/credential-vault/secrets", headers={"X-Actor": "sec", "X-Roles": "security_admin"})
    usable_viewer = client.get(f"/api/v1/credential-vault/secrets/{secret_id}/usable", headers=VIEWER)

    assert viewer.status_code == 403
    assert created.status_code == 201
    assert "PlainSecret" not in created.text
    assert "KEY" not in created.text
    assert listed.status_code == 200
    assert "PlainSecret" not in listed.text
    assert usable_viewer.status_code == 403


def test_credential_vault_api_requires_authenticated_actor(monkeypatch) -> None:
    monkeypatch.setenv("NCP_SECRET_KEY", SECRET_KEY)
    get_settings.cache_clear()
    client = TestClient(app)

    response = client.get("/api/v1/credential-vault/secrets")

    assert response.status_code == 403
