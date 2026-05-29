from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class StoredCredential:
    id: str
    name: str
    username: str
    encrypted_password: str
    encrypted_enable_password: str | None
    auth_type: str
    created_at: datetime
    updated_at: datetime


@dataclass
class StoredAuditEvent:
    id: str
    actor: str
    action: str
    object_type: str
    object_id: str
    device_id: str | None
    job_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    metadata: dict[str, Any]
    created_at: datetime


@dataclass
class StoredBackup:
    id: str
    device_id: str
    job_task_id: str | None
    encrypted_config_text: str
    config_hash: str
    created_at: datetime
    created_by: str


@dataclass
class StoredDeviceLock:
    device_id: str
    job_id: str
    locked_by: str
    locked_at: datetime
    expires_at: datetime


@dataclass
class StoredJobTask:
    id: str
    job_id: str
    device_id: str
    status: str
    attempt: int
    commands: list[str]
    dry_run_device: dict[str, Any]
    sanitized_output: str | None = None
    error: str | None = None
    backup_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass
class StoredJob:
    id: str
    job_type: str
    status: str
    requested_by: str
    approved_by: str | None
    approval_status: str
    dry_run: dict[str, Any]
    input_payload: dict[str, Any]
    created_at: datetime
    approved_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    task_ids: list[str] = field(default_factory=list)


class RuntimeState:
    def __init__(self) -> None:
        self.credentials: dict[str, StoredCredential] = {}
        self.audit_events: list[StoredAuditEvent] = []
        self.backups: dict[str, StoredBackup] = {}
        self.locks: dict[str, StoredDeviceLock] = {}
        self.jobs: dict[str, StoredJob] = {}
        self.job_tasks: dict[str, StoredJobTask] = {}

    def reset(self) -> None:
        self.credentials.clear()
        self.audit_events.clear()
        self.backups.clear()
        self.locks.clear()
        self.jobs.clear()
        self.job_tasks.clear()


runtime_state = RuntimeState()


def get_runtime_state() -> RuntimeState:
    return runtime_state


def reset_runtime_state() -> None:
    runtime_state.reset()

