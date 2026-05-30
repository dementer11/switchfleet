from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.password import PasswordChangeSecret
from app.repositories import coerce_uuid


class PasswordChangeSecretRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_for_job(
        self,
        job_id: str | uuid.UUID,
        encrypted_new_password: str,
        expires_at: datetime | None = None,
    ) -> PasswordChangeSecret:
        secret = PasswordChangeSecret(
            job_id=coerce_uuid(job_id, object_name="Job"),
            encrypted_new_password=encrypted_new_password,
            expires_at=expires_at,
        )
        self.session.add(secret)
        self.session.flush()
        return secret

    def get_for_job(self, job_id: str | uuid.UUID) -> PasswordChangeSecret:
        parsed_job_id = coerce_uuid(job_id, object_name="Job")
        secret = self.session.scalar(select(PasswordChangeSecret).where(PasswordChangeSecret.job_id == parsed_job_id))
        if secret is None:
            raise NotFoundError(f"Password change secret for job {job_id} not found")
        return secret

    def delete_for_job(self, job_id: str | uuid.UUID) -> None:
        secret = self.get_for_job(job_id)
        self.session.delete(secret)
        self.session.flush()

    def set_expires_at(self, job_id: str | uuid.UUID, expires_at: datetime) -> PasswordChangeSecret:
        secret = self.get_for_job(job_id)
        secret.expires_at = expires_at
        self.session.flush()
        return secret
