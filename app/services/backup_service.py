from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import FernetCredentialCipher
from app.db.models.backup import ConfigBackupModel
from app.db.session import SessionLocal
from app.repositories.backups import BackupRepository
from app.repositories.devices import DeviceRepository
from app.schemas.backup import BackupRead
from app.services.audit_service import AuditService
from app.utils.diff import unified_diff
from app.utils.masking import mask_secrets


class BackupService:
    def __init__(
        self,
        session: Session | None = None,
        cipher: FernetCredentialCipher | None = None,
        audit: AuditService | None = None,
    ):
        self.session = session or SessionLocal()
        self.repository = BackupRepository(self.session)
        self.devices = DeviceRepository(self.session)
        self.cipher = cipher or FernetCredentialCipher(get_settings().encryption_key())
        self.audit = audit or AuditService(self.session)

    def hash_config(self, config_text: str) -> str:
        return hashlib.sha256(config_text.encode("utf-8")).hexdigest()

    def create_backup(
        self,
        device_id: str,
        actor: str,
        job_task_id: str | None = None,
        job_id: str | None = None,
        config_text: str | None = None,
    ) -> BackupRead:
        self.devices.get(device_id)
        config = config_text if config_text is not None else self._dummy_config(device_id)
        stored = self.repository.create(
            device_id=device_id,
            job_task_id=job_task_id,
            encrypted_config_text=self.cipher.encrypt(config),
            config_hash=self.hash_config(config),
            created_by=actor,
        )
        self.audit.write(
            actor=actor,
            action="backup.created",
            object_type="backup",
            object_id=str(stored.id),
            device_id=device_id,
            job_id=job_id,
            after={"config_hash": stored.config_hash, "job_task_id": job_task_id},
        )
        return self.read_backup(str(stored.id), include_config=False)

    def list_device_backups(self, device_id: str) -> list[BackupRead]:
        self.devices.get(device_id)
        return [self._read_model(backup, include_config=False) for backup in self.repository.list_by_device(device_id)]

    def read_backup(self, backup_id: str, include_config: bool = True) -> BackupRead:
        return self._read_model(self.repository.get(backup_id), include_config=include_config)

    def diff(self, backup_id: str, other_backup_id: str) -> str:
        left = self._decrypt(self.repository.get(backup_id))
        right = self._decrypt(self.repository.get(other_backup_id))
        return mask_secrets(unified_diff(left, right, fromfile=backup_id, tofile=other_backup_id))

    def _read_model(self, backup: ConfigBackupModel, include_config: bool) -> BackupRead:
        config_text = mask_secrets(self._decrypt(backup)) if include_config else None
        return BackupRead(
            id=str(backup.id),
            device_id=str(backup.device_id),
            job_task_id=str(backup.job_task_id) if backup.job_task_id else None,
            config_hash=backup.config_hash,
            config_text=config_text,
            created_by=backup.created_by,
            created_at=backup.created_at.isoformat(),
        )

    def _decrypt(self, backup: ConfigBackupModel) -> str:
        return self.cipher.decrypt(backup.config_text)

    def _dummy_config(self, device_id: str) -> str:
        return f"! dummy running-config for {device_id}\ninterface Loopback0\n description backup-safe\n"
