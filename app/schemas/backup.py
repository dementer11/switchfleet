from __future__ import annotations

from pydantic import BaseModel


class BackupRead(BaseModel):
    id: str
    device_id: str
    job_task_id: str | None = None
    config_hash: str
    config_text: str | None = None
    created_by: str
    created_at: str


class BackupCreateRequest(BaseModel):
    config_text: str | None = None


class BackupDiffRead(BaseModel):
    backup_id: str
    other_backup_id: str
    diff: str
