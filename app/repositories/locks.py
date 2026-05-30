from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models.lock import DeviceLock
from app.repositories import coerce_uuid


class DeviceLockRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, device_id: str | uuid.UUID) -> DeviceLock | None:
        return self.session.get(DeviceLock, coerce_uuid(device_id, object_name="Device"))

    def create(
        self,
        device_id: str | uuid.UUID,
        job_id: str | uuid.UUID,
        locked_by: str,
        locked_at: datetime,
        expires_at: datetime,
    ) -> DeviceLock:
        lock = DeviceLock(
            device_id=coerce_uuid(device_id, object_name="Device"),
            job_id=coerce_uuid(job_id, object_name="Job"),
            locked_by=locked_by,
            locked_at=locked_at,
            expires_at=expires_at,
        )
        self.session.add(lock)
        self.session.flush()
        return lock

    def delete(self, lock: DeviceLock) -> None:
        self.session.delete(lock)
        self.session.flush()
