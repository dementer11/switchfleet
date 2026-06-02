from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.db.session import SessionLocal
from app.repositories.device_inventory import DeviceInventoryRepository


HEADERS = {"X-Actor": "netadmin", "X-Roles": "network_admin"}


def _device() -> str:
    session = SessionLocal()
    try:
        device, _created = DeviceInventoryRepository(session).upsert_device(
            {
                "management_ip": "10.64.0.1",
                "hostname": "api-sw",
                "vendor": "Cisco",
                "model": "Cat2960-48",
                "site": "HQ",
                "tags": ["api"],
                "driver_name": "CiscoIOSDriver",
            }
        )
        device_id = str(device.id)
        session.commit()
        return device_id
    finally:
        session.close()


def test_config_backup_api_job_run_report_snapshot_diff_drift_and_restore_plan() -> None:
    client = TestClient(app)
    device_id = _device()
    imported = client.post(
        f"/api/v1/config-backups/devices/{device_id}/snapshots/import",
        headers=HEADERS,
        json={"config_type": "running", "source": "imported", "config_text": "hostname old\nusername admin secret VerySecret\n"},
    )
    created = client.post(
        "/api/v1/config-backups/jobs",
        headers=HEADERS,
        json={"name": "api backup", "scope_type": "tag", "scope_filter": {"tag": "api"}},
    )
    run = client.post(f"/api/v1/config-backups/jobs/{created.json()['job']['id']}/run", headers=HEADERS)
    report = client.get(f"/api/v1/config-backups/jobs/{created.json()['job']['id']}/report", headers=HEADERS)
    snapshots = client.get(f"/api/v1/config-backups/devices/{device_id}/snapshots", headers=HEADERS)
    diffs = client.get(f"/api/v1/config-backups/devices/{device_id}/diffs", headers=HEADERS)
    drift = client.get(f"/api/v1/config-backups/devices/{device_id}/drift", headers=HEADERS)
    restore = client.post(
        "/api/v1/config-backups/restore-plans",
        headers=HEADERS,
        json={"device_id": device_id, "target_snapshot_id": snapshots.json()[0]["id"]},
    )

    assert imported.status_code == 201
    assert "VerySecret" not in imported.text
    assert created.status_code == 201
    assert run.status_code == 200
    assert report.json()["job"]["successful_devices"] == 1
    assert len(snapshots.json()) == 2
    assert diffs.json()
    assert drift.json()["drift_detected"] is True
    assert restore.status_code == 201
    assert "RESTORE PREPARATION ONLY" in restore.json()["plan_text"]


def test_config_backup_api_schedules() -> None:
    client = TestClient(app)
    created = client.post(
        "/api/v1/config-backups/schedules",
        headers=HEADERS,
        json={"name": "nightly", "scope_type": "all", "cron_expression": "@daily"},
    )
    schedule_id = created.json()["id"]
    listed = client.get("/api/v1/config-backups/schedules", headers=HEADERS)
    disabled = client.post(f"/api/v1/config-backups/schedules/{schedule_id}/disable", headers=HEADERS)
    enabled = client.post(f"/api/v1/config-backups/schedules/{schedule_id}/enable", headers=HEADERS)
    deleted = client.delete(f"/api/v1/config-backups/schedules/{schedule_id}", headers=HEADERS)

    assert created.status_code == 201
    assert listed.json()[0]["id"] == schedule_id
    assert disabled.json()["enabled"] is False
    assert enabled.json()["enabled"] is True
    assert deleted.status_code == 204
