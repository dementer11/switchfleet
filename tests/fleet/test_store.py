from __future__ import annotations

from pathlib import Path

import pytest

from app.fleet.store import FleetStore


def test_credentials_and_plan_secrets_are_encrypted_and_store_survives_restart(tmp_path: Path) -> None:
    store = FleetStore(tmp_path)
    credential = store.put_credential(name="ops", username="admin", password="NetSecret", enable_password="EnableSecret")
    store.save_plan({"id": "plan-1", "hash": "hash", "operation": "password_change", "new_password_encrypted": store.encrypt("NewSecret")})

    raw = (tmp_path / "state.json").read_text(encoding="utf-8")
    assert all(secret not in raw for secret in ("NetSecret", "EnableSecret", "NewSecret"))
    assert (tmp_path / "local.key").exists()
    assert store.credential(credential["id"]) is not None
    store.close()

    reopened = FleetStore(tmp_path)
    row = reopened.credential("ops")
    assert row is not None
    assert reopened.decrypt(row["encrypted_password"]) == "NetSecret"
    assert reopened.decrypt(row["encrypted_enable_password"]) == "EnableSecret"
    assert reopened.decrypt(reopened.get_plan("plan-1")["new_password_encrypted"]) == "NewSecret"
    reopened.close()


def test_running_jobs_are_marked_failed_after_store_restart(tmp_path: Path) -> None:
    store = FleetStore(tmp_path)
    store.enqueue_job({"id": "job-1", "status": "running", "created_at": "now"}, ["device-1"])

    with pytest.raises(RuntimeError, match="Another SwitchFleet instance"):
        FleetStore(tmp_path)
    assert store.get_job("job-1")["status"] == "running"
    store.close()

    reopened = FleetStore(tmp_path)

    assert reopened.get_job("job-1")["status"] == "failed"
    assert reopened.get_job("job-1")["error"] == "Interrupted by service restart"
    reopened.close()
