from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from app.services.lock_service import LockService
from app.services.runtime_state import utcnow


def test_database_locks_block_active_acquire_and_release_safely() -> None:
    service = LockService()
    device_id = str(uuid4())
    first_job_id = str(uuid4())
    second_job_id = str(uuid4())

    service.acquire(device_id, first_job_id, "alice")
    assert service.is_locked(device_id) is True

    with pytest.raises(RuntimeError):
        service.acquire(device_id, second_job_id, "bob")

    service.release(device_id, actor="alice")
    service.release(device_id, actor="alice")
    lock = service.acquire(device_id, second_job_id, "bob")
    assert lock.job_id == second_job_id


def test_database_locks_replace_expired_rows() -> None:
    service = LockService()
    device_id = str(uuid4())
    service.acquire(device_id, str(uuid4()), "alice")
    stored = service.repository.get(device_id)
    assert stored is not None
    stored.expires_at = utcnow() - timedelta(seconds=1)
    service.session.flush()

    new_job_id = str(uuid4())
    lock = service.acquire(device_id, new_job_id, "bob")

    assert lock.job_id == new_job_id
