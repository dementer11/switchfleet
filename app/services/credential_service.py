from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import FernetCredentialCipher
from app.db.models.credential import Credential
from app.db.session import SessionLocal
from app.repositories.credentials import CredentialRepository
from app.schemas.credential import CredentialCreate, CredentialCreated, CredentialRead
from app.services.audit_service import AuditService


class CredentialService:
    def __init__(
        self,
        session: Session | None = None,
        cipher: FernetCredentialCipher | None = None,
        audit: AuditService | None = None,
    ):
        settings = get_settings()
        self.session = session or SessionLocal()
        self.repository = CredentialRepository(self.session)
        self.cipher = cipher or FernetCredentialCipher(settings.encryption_key())
        self.audit = audit or AuditService(self.session)

    def create(self, credential: CredentialCreate, actor: str) -> CredentialCreated:
        stored = self.repository.create(
            name=credential.name,
            username=credential.username,
            encrypted_password=self.cipher.encrypt(credential.password),
            encrypted_enable_password=self.cipher.encrypt(credential.enable_password) if credential.enable_password else None,
        )
        self.audit.write(
            actor=actor,
            action="credential.created",
            object_type="credential",
            object_id=str(stored.id),
            after={"name": stored.name, "username": stored.username, "has_enable_password": bool(stored.encrypted_enable_password)},
        )
        return CredentialCreated(**self._read_model(stored).model_dump())

    def list(self) -> list[CredentialRead]:
        return [self._read_model(item) for item in self.repository.list()]

    def get(self, credential_id: str) -> CredentialRead:
        return self._read_model(self.repository.get(credential_id))

    def delete(self, credential_id: str, actor: str) -> None:
        stored = self.repository.get(credential_id)
        self.audit.write(
            actor=actor,
            action="credential.deleted",
            object_type="credential",
            object_id=credential_id,
            before={"name": stored.name, "username": stored.username},
        )
        self.repository.delete(stored)

    def decrypt_password_for_execution(self, credential_id: str) -> str:
        return self.cipher.decrypt(self.repository.get(credential_id).encrypted_password)

    def _read_model(self, stored: Credential) -> CredentialRead:
        return CredentialRead(
            id=str(stored.id),
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
