from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.local_web import create_local_web_app
from tests.enterprise.excel_lab_helpers import write_inventory


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _client() -> TestClient:
    return TestClient(create_local_web_app())


def _payload(inventory: Path, state_dir: Path, **extra: object) -> dict[str, object]:
    return {"inventory_path": str(inventory), "state_dir": str(state_dir), **extra}


def test_excel_lab_web_import_does_not_load_db_session() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import app.local_web; print('app.db.session' in sys.modules)",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_excel_lab_web_serves_operator_ui() -> None:
    response = _client().get("/")

    assert response.status_code == 200
    assert "SwitchFleet Local" in response.text
    assert "Production apply disabled" in response.text
    assert "Device IP" in response.text
    assert "execute-apply" in response.text


def test_excel_lab_web_health_reports_local_mode() -> None:
    response = _client().get("/api/local/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["database_required"] is False
    assert payload["production_apply_enabled"] is False
    assert "workflow" in payload["commands"]


def test_excel_lab_web_runs_inventory_runtime_and_planning(tmp_path: Path) -> None:
    inventory = write_inventory(tmp_path / "inventory.xlsx")
    state_dir = tmp_path / ".switchfleet_lab"
    client = _client()

    doctor = client.post("/api/local/doctor", json=_payload(inventory, state_dir))
    summary = client.post("/api/local/summary", json=_payload(inventory, state_dir))
    devices = client.post("/api/local/list", json=_payload(inventory, state_dir))
    runtime = client.post("/api/local/check-runtime", json=_payload(inventory, state_dir, device="192.0.2.67"))
    dry_run = client.post(
        "/api/local/dry-run",
        json=_payload(
            inventory,
            state_dir,
            device="192.0.2.67",
            operation="vlan_create",
            vlan_id=123,
            name="TEST_VLAN",
        ),
    )

    assert doctor.status_code == 200, doctor.text
    assert doctor.json()["database_required"] is False
    assert summary.status_code == 200, summary.text
    assert summary.json()["device_count"] == 1
    assert devices.status_code == 200, devices.text
    assert devices.json()["devices"][0]["device_ip"] == "192.0.2.67"
    assert runtime.status_code == 200, runtime.text
    assert runtime.json()["family"] == "cisco_ios"
    assert dry_run.status_code == 200, dry_run.text
    assert dry_run.json()["device_ip"] == "192.0.2.67"
    assert dry_run.json()["command_hash"]


def test_excel_lab_web_credential_response_and_state_are_secret_safe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-web-test-secret-key")
    get_settings.cache_clear()
    inventory = write_inventory(tmp_path / "inventory.xlsx")
    state_dir = tmp_path / ".switchfleet_lab"
    client = _client()

    response = client.post(
        "/api/local/add-credential",
        json=_payload(
            inventory,
            state_dir,
            name="lab-admin",
            username="admin",
            password="DoNotLeakThisPassword",
            purpose="lab_apply",
        ),
    )

    assert response.status_code == 200, response.text
    text = json.dumps(response.json())
    assert "DoNotLeakThisPassword" not in text
    assert response.json()["credential"]["name"] == "lab-admin"
    state_text = (state_dir / "credentials.json").read_text(encoding="utf-8")
    assert "DoNotLeakThisPassword" not in state_text


def test_excel_lab_web_profile_workflow_matches_cli_safe_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-web-test-secret-key")
    get_settings.cache_clear()
    inventory = write_inventory(
        tmp_path / "inventory.xlsx",
        rows=[
            ["Active", "sw1-lab", "Catalyst 2960", "192.0.2.67", "Cisco", "Switch", "Lab", "NetOps"],
            ["Active", "sw2-lab", "S5735", "192.0.2.68", "Huawei", "Switch", "Lab", "NetOps"],
        ],
    )
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps({"operation": "vlan_create", "credential": "lab-admin", "parameters": {"vlan_id": 123, "name": "WEB"}}),
        encoding="utf-8",
    )
    state_dir = tmp_path / ".switchfleet_lab"
    client = _client()

    response = client.post(
        "/api/local/workflow",
        json=_payload(inventory, state_dir, profile_path=str(profile), with_backup=False),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["workflow"]["device_count"] == 2
    assert payload["workflow"]["real_apply_executed"] is False
    assert payload["workflow"]["backup"] == {"skipped": 2}
    assert payload["workflow"]["dry_run"] == {"ok": 2}
    assert payload["workflow"]["evaluate"] == {"ok": 2}
    assert all(row["device_ip"].startswith("192.0.2.") for row in payload["results"])


def test_excel_lab_web_rejects_unsupported_command(tmp_path: Path) -> None:
    inventory = write_inventory(tmp_path / "inventory.xlsx")
    state_dir = tmp_path / ".switchfleet_lab"

    response = _client().post("/api/local/apply", json=_payload(inventory, state_dir))

    assert response.status_code == 400
    assert "Unsupported Excel web command" in response.json()["detail"]
