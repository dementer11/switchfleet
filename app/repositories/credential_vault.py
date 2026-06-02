from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.credential import CredentialSecret
from app.repositories import coerce_uuid


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CredentialVaultRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        name: str,
        username: str,
        encrypted_payload: str,
        auth_type: str = "password",
        purpose: str | None = None,
        metadata: dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> CredentialSecret:
        now = utcnow()
        secret = CredentialSecret(
            name=name,
            username=username,
            encrypted_payload=encrypted_payload,
            auth_type=auth_type,
            purpose=purpose,
            metadata_=metadata,
            created_by=actor,
            updated_by=actor,
            created_at=now,
            updated_at=now,
        )
        self.session.add(secret)
        self.session.flush()
        return secret

    def get(self, secret_id: str | uuid.UUID) -> CredentialSecret:
        parsed_id = coerce_uuid(secret_id, object_name="Credential secret")
        secret = self.session.get(CredentialSecret, parsed_id)
        if secret is None:
            raise NotFoundError(f"Credential secret {secret_id} not found")
        return secret

    def list(self, active: bool | None = None) -> list[CredentialSecret]:
        statement = select(CredentialSecret)
        if active is not None:
            statement = statement.where(CredentialSecret.active == active)
        return list(self.session.scalars(statement.order_by(CredentialSecret.created_at.desc(), CredentialSecret.name)).all())

    def rotate(self, secret_id: str | uuid.UUID, encrypted_payload: str, actor: str | None = None) -> CredentialSecret:
        secret = self.get(secret_id)
        now = utcnow()
        secret.encrypted_payload = encrypted_payload
        secret.version += 1
        secret.rotated_at = now
        secret.updated_at = now
        secret.updated_by = actor
        secret.active = True
        secret.disabled_at = None
        self.session.flush()
        return secret

    def update_metadata(
        self,
        secret_id: str | uuid.UUID,
        *,
        name: str | None = None,
        username: str | None = None,
        purpose: str | None = None,
        metadata: dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> CredentialSecret:
        secret = self.get(secret_id)
        if name is not None:
            secret.name = name
        if username is not None:
            secret.username = username
        if purpose is not None:
            secret.purpose = purpose
        if metadata is not None:
            secret.metadata_ = metadata
        secret.updated_at = utcnow()
        secret.updated_by = actor
        self.session.flush()
        return secret

    def disable(self, secret_id: str | uuid.UUID, actor: str | None = None) -> CredentialSecret:
        secret = self.get(secret_id)
        secret.active = False
        secret.disabled_at = utcnow()
        secret.updated_at = secret.disabled_at
        secret.updated_by = actor
        self.session.flush()
        return secret

