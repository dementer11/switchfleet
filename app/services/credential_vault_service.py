from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import SecretHandlingError
from app.core.secret_crypto import SecretCrypto
from app.db.models.credential import CredentialSecret
from app.db.session import SessionLocal
from app.repositories.credential_vault import CredentialVaultRepository
from app.schemas.credential_vault import (
    CredentialSecretCreate,
    CredentialSecretRead,
    CredentialSecretRotate,
    CredentialSecretUpdate,
    CredentialSecretUseCheck,
)
from app.services.audit_service import AuditService
from app.services.report_sanitizer import sanitize_report_metadata


class CredentialVaultService:
    def __init__(
        self,
        session: Session | None = None,
        settings: Settings | None = None,
        crypto: SecretCrypto | None = None,
        audit: AuditService | None = None,
    ):
        self.session = session or SessionLocal()
        self.settings = settings or get_settings()
        self.repository = CredentialVaultRepository(self.session)
        self.crypto = crypto
        self.audit = audit or AuditService(self.session)

    def create_secret(self, payload: CredentialSecretCreate, actor: str) -> CredentialSecretRead:
        crypto = self._crypto()
        metadata = sanitize_report_metadata(payload.metadata)
        stored = self.repository.create(
            name=payload.name,
            username=payload.username,
            encrypted_payload=crypto.encrypt_payload(payload.secret),
            auth_type=payload.auth_type,
            purpose=payload.purpose,
            metadata=metadata,
            actor=actor,
        )
        self.audit.write(
            actor=actor,
            action="credential_vault.secret.created",
            object_type="credential_secret",
            object_id=str(stored.id),
            after=self._audit_metadata(stored),
        )
        return self._read(stored)

    def list_metadata(self, active: bool | None = None) -> list[CredentialSecretRead]:
        return [self._read(secret) for secret in self.repository.list(active=active)]

    def get_metadata(self, secret_id: str) -> CredentialSecretRead:
        return self._read(self.repository.get(secret_id))

    def update_metadata(self, secret_id: str, payload: CredentialSecretUpdate, actor: str) -> CredentialSecretRead:
        stored = self.repository.update_metadata(
            secret_id,
            name=payload.name,
            username=payload.username,
            purpose=payload.purpose,
            metadata=sanitize_report_metadata(payload.metadata) if payload.metadata is not None else None,
            actor=actor,
        )
        self.audit.write(
            actor=actor,
            action="credential_vault.secret.metadata_updated",
            object_type="credential_secret",
            object_id=str(stored.id),
            after=self._audit_metadata(stored),
        )
        return self._read(stored)

    def rotate_secret(self, secret_id: str, payload: CredentialSecretRotate, actor: str) -> CredentialSecretRead:
        stored = self.repository.rotate(secret_id, self._crypto().encrypt_payload(payload.secret), actor=actor)
        self.audit.write(
            actor=actor,
            action="credential_vault.secret.rotated",
            object_type="credential_secret",
            object_id=str(stored.id),
            after=self._audit_metadata(stored),
        )
        return self._read(stored)

    def disable_secret(self, secret_id: str, actor: str) -> CredentialSecretRead:
        stored = self.repository.disable(secret_id, actor=actor)
        self.audit.write(
            actor=actor,
            action="credential_vault.secret.disabled",
            object_type="credential_secret",
            object_id=str(stored.id),
            after=self._audit_metadata(stored),
        )
        return self._read(stored)

    def check_usable(self, secret_id: str) -> CredentialSecretUseCheck:
        reasons: list[str] = []
        try:
            stored = self.repository.get(secret_id)
        except Exception as exc:
            return CredentialSecretUseCheck(id=secret_id, usable=False, reasons=[str(exc)])
        if not stored.active:
            reasons.append("Credential secret is disabled")
        if not self.settings.secret_key:
            reasons.append("NCP_SECRET_KEY is required to use credential secrets")
        return CredentialSecretUseCheck(id=str(stored.id), usable=not reasons, reasons=reasons)

    def decrypt_for_execution_after_safety(self, secret_id: str) -> str:
        stored = self.repository.get(secret_id)
        if not stored.active:
            raise SecretHandlingError("Credential secret is disabled")
        return self._crypto().decrypt_payload(stored.encrypted_payload)

    def _crypto(self) -> SecretCrypto:
        if self.crypto is not None:
            return self.crypto
        self.crypto = SecretCrypto(self.settings)
        return self.crypto

    def _audit_metadata(self, stored: CredentialSecret) -> dict[str, Any]:
        return {
            "name": stored.name,
            "username": stored.username,
            "auth_type": stored.auth_type,
            "purpose": stored.purpose,
            "version": stored.version,
            "active": stored.active,
            "has_secret": True,
            "metadata": sanitize_report_metadata(stored.metadata_ or {}),
        }

    def _read(self, stored: CredentialSecret) -> CredentialSecretRead:
        return CredentialSecretRead(
            id=str(stored.id),
            name=stored.name,
            username=stored.username,
            auth_type=stored.auth_type,
            purpose=stored.purpose,
            version=stored.version,
            active=stored.active,
            has_secret=True,
            metadata=sanitize_report_metadata(stored.metadata_ or {}),
            created_by=stored.created_by,
            updated_by=stored.updated_by,
            created_at=stored.created_at.isoformat(),
            updated_at=stored.updated_at.isoformat(),
            rotated_at=stored.rotated_at.isoformat() if stored.rotated_at else None,
            disabled_at=stored.disabled_at.isoformat() if stored.disabled_at else None,
        )

