from datetime import timedelta
from uuid import uuid4

import pytest

from app.services.lock_service import LockService
from app.services.runtime_state import utcnow


def test_lock_service_blocks_active_second_lock_and_releases() -> None:
    service = LockService()
    device_id = str(uuid4())
    service.acquire(device_id, str(uuid4()), "alice")

    with pytest.raises(RuntimeError):
        service.acquire(device_id, str(uuid4()), "bob")

    service.release(device_id, actor="alice")
    service.acquire(device_id, str(uuid4()), "bob")


def test_lock_service_allows_stale_lock_replacement() -> None:
    service = LockService()
    device_id = str(uuid4())
    service.acquire(device_id, str(uuid4()), "alice")
    lock = service.repository.get(device_id)
    assert lock is not None
    lock.expires_at = utcnow() - timedelta(seconds=1)
    service.session.flush()

    new_job_id = str(uuid4())
    new_lock = service.acquire(device_id, new_job_id, "bob")

    assert new_lock.job_id == new_job_id
