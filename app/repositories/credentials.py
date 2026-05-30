from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.credential import Credential
from app.repositories import coerce_uuid


class CredentialRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        name: str,
        username: str,
        encrypted_password: str,
        encrypted_enable_password: str | None,
        auth_type: str = "password",
    ) -> Credential:
        credential = Credential(
            name=name,
            username=username,
            encrypted_password=encrypted_password,
            encrypted_enable_password=encrypted_enable_password,
            auth_type=auth_type,
        )
        self.session.add(credential)
        self.session.flush()
        return credential

    def list(self) -> list[Credential]:
        return list(self.session.scalars(select(Credential).order_by(Credential.created_at, Credential.name)).all())

    def get(self, credential_id: str | uuid.UUID) -> Credential:
        parsed_id = coerce_uuid(credential_id, object_name="Credential")
        credential = self.session.get(Credential, parsed_id)
        if credential is None:
            raise NotFoundError(f"Credential {credential_id} not found")
        return credential

    def delete(self, credential: Credential) -> None:
        self.session.delete(credential)
        self.session.flush()
