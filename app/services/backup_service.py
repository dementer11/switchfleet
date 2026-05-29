from __future__ import annotations

import hashlib

from app.core.config import get_settings
from app.core.crypto import FernetCredentialCipher
from app.core.exceptions import NotFoundError
from app.schemas.backup import BackupRead
from app.services.audit_service import AuditService
from app.services.runtime_state import RuntimeState, StoredBackup, get_runtime_state, new_id, utcnow
from app.utils.diff import unified_diff
from app.utils.masking import mask_secrets


class BackupService:
    def __init__(
        self,
        state: RuntimeState | None = None,
        cipher: FernetCredentialCipher | None = None,
        audit: AuditService | None = None,
    ):
        self.state = state or get_runtime_state()
        self.cipher = cipher or FernetCredentialCipher(get_settings().encryption_key())
        self.audit = audit or AuditService(self.state)

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
        config = config_text if config_text is not None else self._dummy_config(device_id)
        stored = StoredBackup(
            id=new_id(),
            device_id=device_id,
            job_task_id=job_task_id,
            encrypted_config_text=self.cipher.encrypt(config),
            config_hash=self.hash_config(config),
            created_at=utcnow(),
            created_by=actor,
        )
        self.state.backups[stored.id] = stored
        self.audit.write(
            actor=actor,
            action="backup.created",
            object_type="backup",
            object_id=stored.id,
            device_id=device_id,
            job_id=job_id,
            after={"config_hash": stored.config_hash, "job_task_id": job_task_id},
        )
        return self.read_backup(stored.id, include_config=False)

    def list_device_backups(self, device_id: str) -> list[BackupRead]:
        return [
            self._read_model(backup, include_config=False)
            for backup in self.state.backups.values()
            if backup.device_id == device_id
        ]

    def read_backup(self, backup_id: str, include_config: bool = True) -> BackupRead:
        return self._read_model(self._stored(backup_id), include_config=include_config)

    def diff(self, backup_id: str, other_backup_id: str) -> str:
        left = self._decrypt(self._stored(backup_id))
        right = self._decrypt(self._stored(other_backup_id))
        return mask_secrets(unified_diff(left, right, fromfile=backup_id, tofile=other_backup_id))

    def _stored(self, backup_id: str) -> StoredBackup:
        stored = self.state.backups.get(backup_id)
        if stored is None:
            raise NotFoundError(f"Backup {backup_id} not found")
        return stored

    def _read_model(self, backup: StoredBackup, include_config: bool) -> BackupRead:
        config_text = mask_secrets(self._decrypt(backup)) if include_config else None
        return BackupRead(
            id=backup.id,
            device_id=backup.device_id,
            job_task_id=backup.job_task_id,
            config_hash=backup.config_hash,
            config_text=config_text,
            created_by=backup.created_by,
            created_at=backup.created_at.isoformat(),
        )

    def _decrypt(self, backup: StoredBackup) -> str:
        return self.cipher.decrypt(backup.encrypted_config_text)

    def _dummy_config(self, device_id: str) -> str:
        return f"! dummy running-config for {device_id}\ninterface Loopback0\n description backup-safe\n"
