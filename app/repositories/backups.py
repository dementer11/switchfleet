from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.backup import ConfigBackupModel
from app.repositories import coerce_uuid, optional_uuid


class BackupRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        device_id: str | uuid.UUID,
        encrypted_config_text: str,
        config_hash: str,
        created_by: str,
        job_task_id: str | uuid.UUID | None = None,
    ) -> ConfigBackupModel:
        backup = ConfigBackupModel(
            device_id=coerce_uuid(device_id, object_name="Device"),
            job_task_id=optional_uuid(job_task_id, object_name="Job task"),
            config_text=encrypted_config_text,
            config_hash=config_hash,
            created_by=created_by,
        )
        self.session.add(backup)
        self.session.flush()
        return backup

    def get(self, backup_id: str | uuid.UUID) -> ConfigBackupModel:
        parsed_id = coerce_uuid(backup_id, object_name="Backup")
        backup = self.session.get(ConfigBackupModel, parsed_id)
        if backup is None:
            raise NotFoundError(f"Backup {backup_id} not found")
        return backup

    def list_by_device(self, device_id: str | uuid.UUID) -> list[ConfigBackupModel]:
        parsed_id = coerce_uuid(device_id, object_name="Device")
        return list(
            self.session.scalars(
                select(ConfigBackupModel)
                .where(ConfigBackupModel.device_id == parsed_id)
                .order_by(ConfigBackupModel.created_at.desc())
            ).all()
        )
