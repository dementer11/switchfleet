from __future__ import annotations

from pathlib import Path

from app.services.file_lab_state import FileLabState, FileLabStateError


def test_file_lab_state_writes_json_jsonl_and_backups(tmp_path: Path) -> None:
    state = FileLabState(tmp_path / ".switchfleet_lab")
    dry_run = state.save_dry_run({"device_id": "dev1", "command_hash": "hash1"})
    backup = state.save_backup("dev1", "hostname lab\nusername admin secret <redacted>", {"config_hash": "hash"})
    state.save_lab_validation({"device_id": "dev1", "capability": "vlan_create"})
    state.reserve_lock("dev1", "test")
    state.release_locks("dev1")
    event = state.append_audit(action="test", actor="tester", object_type="device", object_id="dev1", metadata={"password": "SHOULD_NOT_LEAK"})

    assert dry_run["command_hash"] == "hash1"
    assert backup["sanitized"] is True
    assert state.latest_backup_for("dev1") is not None
    assert state.latest_validation_for("dev1", "vlan_create") is not None
    assert event["metadata"]["password"] == "<redacted>"
    assert state.audit_tail(1)[0]["id"] == event["id"]


def test_file_lab_state_reports_corrupt_json(tmp_path: Path) -> None:
    state = FileLabState(tmp_path / ".switchfleet_lab")
    state.paths.dry_runs.write_text("{not-json", encoding="utf-8")

    try:
        state.read_dry_runs()
    except FileLabStateError as exc:
        assert "corrupt json" in str(exc).casefold()
    else:
        raise AssertionError("Corrupt file state was not rejected")
