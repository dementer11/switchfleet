from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.repositories.locks import DeviceLockRepository
from app.services.audit_service import AuditService


@dataclass(frozen=True)
class InMemoryDeviceLock:
    device_id: str
    job_id: str
    locked_by: str
    expires_at: datetime


class LockService:
    def __init__(self, session: Session | None = None, audit: AuditService | None = None) -> None:
        self.session = session or SessionLocal()
        self.repository = DeviceLockRepository(self.session)
        self.audit = audit or AuditService(self.session)

    def acquire(self, device_id: str, job_id: str, actor: str, ttl_seconds: int = 900) -> InMemoryDeviceLock:
        now = datetime.now(timezone.utc)
        existing = self.repository.get(device_id)
        if existing and _aware(existing.expires_at) > now:
            raise RuntimeError(f"Device {device_id} is already locked")
        if existing is not None:
            self.repository.delete(existing)
        stored = self.repository.create(
            device_id=device_id,
            job_id=job_id,
            locked_by=actor,
            locked_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
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
            device_id=str(stored.device_id),
            job_id=str(stored.job_id),
            locked_by=stored.locked_by,
            expires_at=_aware(stored.expires_at),
        )

    def release(self, device_id: str, actor: str = "system") -> None:
        existing = self.repository.get(device_id)
        if existing is not None:
            self.audit.write(
                actor=actor,
                action="device.unlocked",
                object_type="device_lock",
                object_id=device_id,
                device_id=device_id,
                job_id=str(existing.job_id),
                before={"locked_by": existing.locked_by, "expires_at": existing.expires_at.isoformat()},
            )
            self.repository.delete(existing)

    def is_locked(self, device_id: str) -> bool:
        existing = self.repository.get(device_id)
        if existing is None:
            return False
        if _aware(existing.expires_at) <= datetime.now(timezone.utc):
            self.repository.delete(existing)
            return False
        return True


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
