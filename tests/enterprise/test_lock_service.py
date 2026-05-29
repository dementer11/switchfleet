from datetime import timedelta

import pytest

from app.services.lock_service import LockService
from app.services.runtime_state import get_runtime_state, utcnow


def test_lock_service_blocks_active_second_lock_and_releases() -> None:
    service = LockService()
    service.acquire("device-1", "job-1", "alice")

    with pytest.raises(RuntimeError):
        service.acquire("device-1", "job-2", "bob")

    service.release("device-1", actor="alice")
    service.acquire("device-1", "job-2", "bob")


def test_lock_service_allows_stale_lock_replacement() -> None:
    service = LockService()
    service.acquire("device-1", "job-1", "alice")
    get_runtime_state().locks["device-1"].expires_at = utcnow() - timedelta(seconds=1)

    lock = service.acquire("device-1", "job-2", "bob")

    assert lock.job_id == "job-2"

