from __future__ import annotations

from app.core.config import get_settings
from app.core.crypto import FernetCredentialCipher
from app.core.exceptions import NotFoundError
from app.schemas.credential import CredentialCreate, CredentialCreated, CredentialRead
from app.services.audit_service import AuditService
from app.services.runtime_state import RuntimeState, StoredCredential, get_runtime_state, new_id, utcnow


class CredentialService:
    def __init__(
        self,
        state: RuntimeState | None = None,
        cipher: FernetCredentialCipher | None = None,
        audit: AuditService | None = None,
    ):
        settings = get_settings()
        self.state = state or get_runtime_state()
        self.cipher = cipher or FernetCredentialCipher(settings.encryption_key())
        self.audit = audit or AuditService(self.state)

    def create(self, credential: CredentialCreate, actor: str) -> CredentialCreated:
        now = utcnow()
        stored = StoredCredential(
            id=new_id(),
            name=credential.name,
            username=credential.username,
            encrypted_password=self.cipher.encrypt(credential.password),
            encrypted_enable_password=self.cipher.encrypt(credential.enable_password) if credential.enable_password else None,
            auth_type="password",
            created_at=now,
            updated_at=now,
        )
        self.state.credentials[stored.id] = stored
        self.audit.write(
            actor=actor,
            action="credential.created",
            object_type="credential",
            object_id=stored.id,
            after={"name": stored.name, "username": stored.username, "has_enable_password": bool(stored.encrypted_enable_password)},
        )
        return CredentialCreated(**self._read_model(stored).model_dump())

    def list(self) -> list[CredentialRead]:
        return [self._read_model(item) for item in self.state.credentials.values()]

    def get(self, credential_id: str) -> CredentialRead:
        return self._read_model(self._stored(credential_id))

    def delete(self, credential_id: str, actor: str) -> None:
        stored = self._stored(credential_id)
        del self.state.credentials[credential_id]
        self.audit.write(
            actor=actor,
            action="credential.deleted",
            object_type="credential",
            object_id=credential_id,
            before={"name": stored.name, "username": stored.username},
        )

    def decrypt_password_for_execution(self, credential_id: str) -> str:
        return self.cipher.decrypt(self._stored(credential_id).encrypted_password)

    def _stored(self, credential_id: str) -> StoredCredential:
        stored = self.state.credentials.get(credential_id)
        if stored is None:
            raise NotFoundError(f"Credential {credential_id} not found")
        return stored

    def _read_model(self, stored: StoredCredential) -> CredentialRead:
        return CredentialRead(
            id=stored.id,
            name=stored.name,
            username=stored.username,
            auth_type=stored.auth_type,
            has_enable_password=stored.encrypted_enable_password is not None,
            created_at=stored.created_at.isoformat(),
            updated_at=stored.updated_at.isoformat(),
        )

    def sanitize_created(self, credential: CredentialCreate) -> CredentialRead:
        created = self.create(credential, actor="system")
        return CredentialRead(**created.model_dump(exclude={"password", "enable_password"}))
