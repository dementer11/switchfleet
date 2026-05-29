from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.services.audit_service import AuditService
from app.services.runtime_state import RuntimeState, StoredDeviceLock, get_runtime_state


@dataclass(frozen=True)
class InMemoryDeviceLock:
    device_id: str
    job_id: str
    locked_by: str
    expires_at: datetime


class LockService:
    def __init__(self, state: RuntimeState | None = None, audit: AuditService | None = None) -> None:
        self.state = state or get_runtime_state()
        self.audit = audit or AuditService(self.state)

    def acquire(self, device_id: str, job_id: str, actor: str, ttl_seconds: int = 900) -> InMemoryDeviceLock:
        existing = self.state.locks.get(device_id)
        now = datetime.now(timezone.utc)
        if existing and existing.expires_at > now:
            raise RuntimeError(f"Device {device_id} is already locked")
        stored = StoredDeviceLock(
            device_id=device_id,
            job_id=job_id,
            locked_by=actor,
            locked_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        self.state.locks[device_id] = stored
        self.audit.write(
            actor=actor,
            action="device.locked",
            object_type="device_lock",
            object_id=device_id,
            device_id=device_id,
            job_id=job_id,
            after={"expires_at": stored.expires_at.isoformat()},
        )
        return InMemoryDeviceLock(
            device_id=stored.device_id,
            job_id=stored.job_id,
            locked_by=stored.locked_by,
            expires_at=stored.expires_at,
        )

    def release(self, device_id: str, actor: str = "system") -> None:
        existing = self.state.locks.pop(device_id, None)
        if existing is not None:
            self.audit.write(
                actor=actor,
                action="device.unlocked",
                object_type="device_lock",
                object_id=device_id,
                device_id=device_id,
                job_id=existing.job_id,
                before={"locked_by": existing.locked_by, "expires_at": existing.expires_at.isoformat()},
            )

    def is_locked(self, device_id: str) -> bool:
        existing = self.state.locks.get(device_id)
        if existing is None:
            return False
        if existing.expires_at <= datetime.now(timezone.utc):
            self.state.locks.pop(device_id, None)
            return False
        return True
