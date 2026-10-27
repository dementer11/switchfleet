from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.fleet.api import create_fleet_app


class FakeEngine:
    version = "fake-1"

    def __init__(self):
        self.runs = []

    def available(self):
        return {"available": True, "version": self.version, "error": None}

    def run(self, plans, credentials, on_event=None, is_cancelled=None, forks=5):
        self.runs.append((plans, credentials, forks))
        if on_event:
            on_event({"event": "fake completed"})
        return [
            {"device_id": plan["device_id"], "ip_address": plan["ip_address"], "status": "succeeded", "output": "ok", "backup_text": "hostname sw1" if plan["operation"] == "backup" else None}
            for plan in plans
        ]


def _client(tmp_path: Path, engine: FakeEngine | None = None) -> TestClient:
    return TestClient(create_fleet_app(tmp_path, engine or FakeEngine()))


def _upload(client: TestClient, *, ip: str = "192.0.2.1", filename: str = "../../inventory.json") -> dict:
    body = json.dumps([{"id": "sw1", "label": "switch one", "ip_address": ip, "vendor": "Cisco", "model": "Catalyst 2960", "family": "cisco_ios", "original_model": "CAT2960"}]).encode()
    response = client.post("/api/fleet/inventory", params={"filename": filename}, content=body, headers={"content-type": "application/json"})
    assert response.status_code == 200, response.text
    return response.json()


def _credential(client: TestClient) -> dict:
    response = client.post("/api/fleet/credentials", json={"name": "ops", "username": "admin", "password": "DoNotEchoSecret"})
    assert response.status_code == 200, response.text
    assert "password" not in response.json()
    return response.json()


def _wait_for_job(client: TestClient, job_id: str) -> dict:
    for _ in range(100):
        response = client.get(f"/api/fleet/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] not in {"queued", "running"}:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_inventory_upload_generates_safe_path_and_preserves_original_values(tmp_path: Path) -> None:
    client = _client(tmp_path)

    payload = _upload(client)

    assert payload["devices"][0]["ip_address"] == "192.0.2.1"
    assert payload["devices"][0]["original_model"] == "CAT2960"
    assert len(list(tmp_path.glob("inventory-*"))) == 1
    assert all(path.parent.resolve() == tmp_path.resolve() for path in tmp_path.glob("inventory-*"))
    assert client.get("/api/fleet/inventory").json() == payload


def test_inventory_rejects_duplicate_ip_and_invalid_ip(tmp_path: Path) -> None:
    client = _client(tmp_path)
    body = json.dumps([
        {"id": "one", "ip_address": "192.0.2.1", "family": "cisco_ios"},
        {"id": "two", "ip_address": "192.0.2.1", "family": "cisco_ios"},
    ])
    response = client.post("/api/fleet/inventory?filename=devices.json", content=body, headers={"content-type": "application/json"})
    assert response.status_code == 400
    assert "Duplicate IP" in response.json()["detail"]

    duplicate_id = client.post("/api/fleet/inventory?filename=devices.json", json=[
        {"id": "same", "ip_address": "192.0.2.1", "family": "cisco_ios"},
        {"id": "same", "ip_address": "192.0.2.2", "family": "cisco_ios"},
    ])
    assert duplicate_id.status_code == 400
    assert "Duplicate device ID" in duplicate_id.json()["detail"]

    response = client.post("/api/fleet/inventory?filename=devices.json", json=[{"ip_address": "not-an-ip"}])
    assert response.status_code == 400


def test_create_job_validates_plan_hash_and_returns_safe_backup(tmp_path: Path) -> None:
    engine = FakeEngine()
    client = _client(tmp_path, engine)
    _upload(client)
    credential = _credential(client)
    plan = client.post("/api/fleet/plans", json={"device_ids": ["sw1"], "operation": "backup", "parameters": {}, "credential_ref": credential["id"]}).json()
    bad_hash = client.post("/api/fleet/jobs", json={"plan_id": plan["id"], "plan_hash": "bad", "confirmed": False})
    assert bad_hash.status_code == 400

    queued = client.post("/api/fleet/jobs", json={"plan_id": plan["id"], "plan_hash": plan["hash"], "confirmed": False})
    assert queued.status_code == 200, queued.text
    job = _wait_for_job(client, queued.json()["id"])
    assert job["status"] == "succeeded"
    backup = client.get(f"/api/fleet/jobs/{job['id']}/backups/sw1")
    assert backup.status_code == 200
    assert backup.text == "hostname sw1"
    assert "switchfleet-backup-192.0.2.1.txt" in backup.headers["content-disposition"]
    summary = client.get("/api/fleet/jobs").json()["jobs"][0]
    assert summary["operation"] == "backup"
    assert summary["device_count"] == 1
    assert summary["success_count"] == 1
    assert summary["failure_count"] == 0
    events = client.get("/api/fleet/audit").json()["events"]
    assert all(event.get("created_at") for event in events)
    assert any(event["action"] == "job.completed" for event in events)


def test_mutating_job_requires_confirmation_and_password_is_not_echoed(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _upload(client)
    credential = _credential(client)
    secret = "NewDevicePassword!"
    plan_response = client.post("/api/fleet/plans", json={
        "device_ids": ["sw1"], "operation": "password_change", "credential_ref": credential["id"],
        "parameters": {"username": "admin", "new_password": secret},
    })
    assert plan_response.status_code == 200, plan_response.text
    assert secret not in plan_response.text
    plan = plan_response.json()
    response = client.post("/api/fleet/jobs", json={"plan_id": plan["id"], "plan_hash": plan["hash"], "confirmed": False})
    assert response.status_code == 400
    assert secret not in response.text
    assert secret not in (tmp_path / "state.json").read_text(encoding="utf-8")


def test_configure_plan_commands_are_encrypted_at_rest_and_redacted_in_preview(tmp_path: Path) -> None:
    secret = "OnlySyntheticPassword123"
    app = create_fleet_app(tmp_path, FakeEngine())
    with TestClient(app) as client:
        _upload(client)
        response = client.post("/api/fleet/plans", json={
            "device_ids": ["sw1"],
            "operation": "configure",
            "parameters": {"commands": [f"username admin secret {secret}"]},
        })
        assert response.status_code == 200, response.text
        plan = response.json()
        assert secret not in response.text
        assert "secret <redacted>" in plan["devices"][0]["commands"][0]
        raw_state = (tmp_path / "state.json").read_text(encoding="utf-8")
        assert secret not in raw_state
        stored_plan = app.state.fleet_service.store.get_plan(plan["id"])
        assert stored_plan["devices"][0]["commands"] == [f"username admin secret {secret}"]


def test_job_rejects_missing_credential_and_engine_unavailable(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _upload(client)
    plan = client.post("/api/fleet/plans", json={"device_ids": ["sw1"], "operation": "facts", "parameters": {}}).json()
    missing = client.post("/api/fleet/jobs", json={"plan_id": plan["id"], "plan_hash": plan["hash"], "confirmed": False})
    assert missing.status_code == 400

    class Unavailable(FakeEngine):
        def available(self):
            return {"available": False, "version": None, "error": "offline"}

    client = _client(tmp_path / "unavailable", Unavailable())
    _upload(client)
    credential = _credential(client)
    plan = client.post("/api/fleet/plans", json={"device_ids": ["sw1"], "operation": "facts", "parameters": {}, "credential_ref": credential["id"]}).json()
    rejected = client.post("/api/fleet/jobs", json={"plan_id": plan["id"], "plan_hash": plan["hash"], "confirmed": False})
    assert rejected.status_code == 503


def test_username_matching_device_id_is_not_redacted(tmp_path: Path) -> None:
    client = _client(tmp_path)
    imported = client.post("/api/fleet/inventory?filename=inventory.json", json=[
        {"id": "admin", "label": "admin", "ip_address": "192.0.2.9", "vendor": "Cisco", "model": "Catalyst 2960", "family": "cisco_ios"},
    ])
    assert imported.status_code == 200
    credential = client.post("/api/fleet/credentials", json={"name": "ops", "username": "admin", "password": "OnlyPasswordSecret"})
    assert credential.status_code == 200
    plan = client.post("/api/fleet/plans", json={"device_ids": ["admin"], "operation": "facts", "parameters": {}, "credential_ref": credential.json()["id"]}).json()
    queued = client.post("/api/fleet/jobs", json={"plan_id": plan["id"], "plan_hash": plan["hash"], "confirmed": False}).json()
    job = _wait_for_job(client, queued["id"])

    assert job["status"] == "succeeded"
    assert job["results"][0]["device_id"] == "admin"
    assert "OnlyPasswordSecret" not in json.dumps(job)
    invalid = client.post("/api/fleet/credentials", json={"name": "bad", "username": "admin", "password": "pw", "enable_password": {"bad": "type"}})
    assert invalid.status_code == 400


def test_device_patch_profiles_audit_and_write_origin_policy(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _upload(client)
    credential = _credential(client)
    patched = client.patch("/api/fleet/devices/sw1", json={"family": "hpe_comware", "port": 2222, "credential_ref": credential["id"]})
    assert patched.status_code == 200
    assert patched.json()["port"] == 2222
    assert client.patch("/api/fleet/devices/sw1", json={"family": "not-real"}).status_code == 400
    assert client.get("/api/fleet/profiles").json()["profiles"]
    assert client.get("/api/fleet/audit").json()["events"]

    forbidden = client.post("/api/fleet/credentials", headers={"origin": "https://evil.example"}, json={"name": "x", "username": "u", "password": "secret"})
    assert forbidden.status_code == 403
    mismatched_local_port = client.post("/api/fleet/credentials", headers={"origin": "http://testserver:9999"}, json={"name": "x", "username": "u", "password": "secret"})
    assert mismatched_local_port.status_code == 403


def test_csv_inventory_infers_family_from_vendor_and_model(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/api/fleet/inventory?filename=inventory.csv",
        content="IP Address,Vendor,Model\n192.0.2.5,Cisco,CAT2960\n",
        headers={"content-type": "text/csv"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["devices"][0]["family"] == "cisco_ios"


def test_device_locks_use_canonical_ip_and_port_across_inventory_reimport(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()

    class SlowEngine(FakeEngine):
        def run(self, plans, credentials, on_event=None, is_cancelled=None, forks=5):
            entered.set()
            release.wait(timeout=2)
            return super().run(plans, credentials, on_event=on_event, is_cancelled=is_cancelled, forks=forks)

    client = _client(tmp_path, SlowEngine())
    _upload(client, filename="first.json")
    credential = _credential(client)
    plan = client.post("/api/fleet/plans", json={"device_ids": ["sw1"], "operation": "facts", "parameters": {}, "credential_ref": credential["id"]}).json()
    created = client.post("/api/fleet/jobs", json={"plan_id": plan["id"], "plan_hash": plan["hash"], "confirmed": False})
    assert created.status_code == 200
    assert entered.wait(timeout=1)

    imported = client.post("/api/fleet/inventory?filename=second.json", json=[
        {"id": "new-id", "ip_address": "192.0.2.1", "vendor": "Cisco", "model": "Catalyst 2960", "family": "cisco_ios"},
    ])
    assert imported.status_code == 200
    second_plan = client.post("/api/fleet/plans", json={"device_ids": ["new-id"], "operation": "facts", "parameters": {}, "credential_ref": credential["id"]}).json()
    duplicate_job = client.post("/api/fleet/jobs", json={"plan_id": second_plan["id"], "plan_hash": second_plan["hash"], "confirmed": False})
    assert duplicate_job.status_code == 400
    release.set()


def test_cancel_request_records_timestamps_and_audit(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()

    class SlowEngine(FakeEngine):
        def run(self, plans, credentials, on_event=None, is_cancelled=None, forks=5):
            entered.set()
            release.wait(timeout=2)
            return super().run(plans, credentials, on_event=on_event, is_cancelled=is_cancelled, forks=forks)

    client = _client(tmp_path, SlowEngine())
    _upload(client)
    credential = _credential(client)
    plan = client.post("/api/fleet/plans", json={"device_ids": ["sw1"], "operation": "facts", "parameters": {}, "credential_ref": credential["id"]}).json()
    queued = client.post("/api/fleet/jobs", json={"plan_id": plan["id"], "plan_hash": plan["hash"], "confirmed": False}).json()
    assert entered.wait(timeout=1)
    requested = client.post(f"/api/fleet/jobs/{queued['id']}/cancel")
    assert requested.status_code == 200
    release.set()

    job = _wait_for_job(client, queued["id"])
    assert job["status"] == "cancelled"
    assert job["started_at"] and job["cancel_requested_at"] and job["finished_at"]
    events = client.get("/api/fleet/audit").json()["events"]
    assert any(event["action"] == "job.cancel_requested" and event.get("created_at") for event in events)
    assert any(event["action"] == "job.completed" and event.get("metadata", {}).get("status") == "cancelled" for event in events)


def test_shutdown_waits_for_engine_before_releasing_instance_lock(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()
    shutdown_complete = threading.Event()

    class BlockingEngine(FakeEngine):
        def run(self, plans, credentials, on_event=None, is_cancelled=None, forks=5):
            entered.set()
            release.wait(timeout=5)
            return super().run(plans, credentials, on_event=on_event, is_cancelled=is_cancelled, forks=forks)

    first_app = create_fleet_app(tmp_path, BlockingEngine())
    first_client = TestClient(first_app)
    first_client.__enter__()
    _upload(first_client)
    credential = _credential(first_client)
    plan = first_client.post("/api/fleet/plans", json={"device_ids": ["sw1"], "operation": "facts", "parameters": {}, "credential_ref": credential["id"]}).json()
    queued = first_client.post("/api/fleet/jobs", json={"plan_id": plan["id"], "plan_hash": plan["hash"], "confirmed": False}).json()
    assert entered.wait(timeout=1)

    def stop_first_app() -> None:
        first_client.__exit__(None, None, None)
        shutdown_complete.set()

    stop_thread = threading.Thread(target=stop_first_app)
    stop_thread.start()
    first_store = first_app.state.fleet_service.store
    deadline = time.monotonic() + 1
    while not first_store.is_cancelled(queued["id"]) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert first_store.is_cancelled(queued["id"])
    assert not shutdown_complete.wait(timeout=0.05)
    try:
        create_fleet_app(tmp_path, FakeEngine())
    except RuntimeError as exc:
        assert "already owns" in str(exc)
    else:
        raise AssertionError("second app acquired the data directory while the first engine was alive")
    finally:
        release.set()
    assert shutdown_complete.wait(timeout=2)
    stop_thread.join(timeout=1)

    second_app = create_fleet_app(tmp_path, FakeEngine())
    with TestClient(second_app) as second_client:
        job = second_client.get(f"/api/fleet/jobs/{queued['id']}").json()
        assert job["status"] == "cancelled"
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["locks"] == {}
