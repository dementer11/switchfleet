from __future__ import annotations

from pathlib import Path

import pytest

from app.core.exceptions import SafetyError
from app.services import file_lab_state as file_lab_state_module
from app.services.file_lab_state import FileLabState, FileLabStateError


def test_file_lab_state_writes_json_jsonl_and_backups(tmp_path: Path) -> None:
    state = FileLabState(tmp_path / ".switchfleet_lab")
    dry_run = state.save_dry_run(
        {
            "device_id": "dev1",
            "command_hash": "hash1",
            "password": "SHOULD_NOT_LEAK",
            "commands": [{"command": "username admin secret SHOULD_NOT_LEAK"}],
        }
    )
    backup = state.save_backup(
        "dev1",
        "hostname lab\nusername admin secret VerySecret",
        {"source": "unit-test", "token": "SHOULD_NOT_LEAK"},
    )
    validation = state.save_lab_validation(
        {"device_id": "dev1", "capability": "vlan_create", "credential_secret": "SHOULD_NOT_LEAK"}
    )
    evaluation = state.save_evaluation(
        {
            "device_id": "dev1",
            "operation": "vlan_create",
            "command_hash": "hash1",
            "denied_gates": ["lab_validation"],
            "reasons": ["password SHOULD_NOT_LEAK"],
        }
    )
    execution = state.save_execution(
        {
            "device_id": "dev1",
            "error": "password SHOULD_NOT_LEAK",
            "commands": [{"command": "username admin secret SHOULD_NOT_LEAK"}],
        }
    )
    state.reserve_lock("dev1", "test")
    state.release_locks("dev1")
    event = state.append_audit(action="test", actor="tester", object_type="device", object_id="dev1", metadata={"password": "SHOULD_NOT_LEAK"})
    stored_backup = (state.paths.root / backup["config_path"]).read_text(encoding="utf-8")

    assert dry_run["command_hash"] == "hash1"
    assert dry_run["password"] == "<redacted>"
    assert "SHOULD_NOT_LEAK" not in state.paths.dry_runs.read_text(encoding="utf-8")
    assert backup["sanitized"] is True
    assert "VerySecret" not in stored_backup
    assert "<redacted>" in stored_backup
    assert backup["config_hash"]
    assert backup["redaction_types"]
    assert state.latest_backup_for("dev1") is not None
    assert state.latest_evaluation_for("dev1", "vlan_create", "hash1")["id"] == evaluation["id"]
    assert "SHOULD_NOT_LEAK" not in state.paths.evaluations.read_text(encoding="utf-8")
    assert state.latest_validation_for("dev1", "vlan_create")["id"] == validation["id"]
    assert "SHOULD_NOT_LEAK" not in state.paths.lab_validations.read_text(encoding="utf-8")
    assert "SHOULD_NOT_LEAK" not in (state.paths.executions / f"{execution['id']}.json").read_text(encoding="utf-8")
    assert "SHOULD_NOT_LEAK" not in (state.paths.backups / "index.json").read_text(encoding="utf-8")
    assert event["metadata"]["password"] == "<redacted>"
    assert state.audit_tail(1)[0]["id"] == event["id"]


def test_file_lab_state_keeps_same_hash_for_different_devices(tmp_path: Path) -> None:
    state = FileLabState(tmp_path / ".switchfleet_lab")
    state.save_dry_run({"device_id": "dev1", "operation": "vlan_create", "command_hash": "same-hash"})
    state.save_dry_run({"device_id": "dev2", "operation": "vlan_create", "command_hash": "same-hash"})

    dry_runs = state.read_dry_runs()

    assert {(item["device_id"], item["command_hash"]) for item in dry_runs} == {
        ("dev1", "same-hash"),
        ("dev2", "same-hash"),
    }


def test_file_lab_state_does_not_treat_missing_or_empty_backup_files_as_usable(tmp_path: Path) -> None:
    state = FileLabState(tmp_path / ".switchfleet_lab")
    backup = state.save_backup("dev1", "hostname sw1", {"source": "unit-test"})
    config_path = state.paths.root / backup["config_path"]

    assert state.latest_backup_for("dev1") is not None
    config_path.unlink()
    assert state.latest_backup_for("dev1") is None

    empty = state.save_backup("dev1", "hostname sw1", {"source": "unit-test"})
    empty_path = state.paths.root / empty["config_path"]
    empty_path.write_text("", encoding="utf-8")
    assert state.latest_backup_for("dev1") is None


def test_file_lab_state_lock_reservation_blocks_a_second_process_before_json_persistence(tmp_path: Path) -> None:
    state = FileLabState(tmp_path / ".switchfleet_lab")
    competing_state = FileLabState(state.paths.root)
    original_write = state._write_json
    attempted_race = False

    def write_with_competing_reservation(path: Path, payload: dict[str, object]) -> None:
        nonlocal attempted_race
        if path == state.paths.locks and not attempted_race:
            attempted_race = True
            with pytest.raises(SafetyError, match="active lab lock"):
                competing_state.reserve_lock("dev1", "competing process")
        original_write(path, payload)

    state._write_json = write_with_competing_reservation  # type: ignore[method-assign]

    state.reserve_lock("dev1", "first process")

    assert attempted_race is True
    assert state._lockfile_for("dev1").exists()
    state.release_locks("dev1")
    assert not state._lockfile_for("dev1").exists()
    assert competing_state.reserve_lock("dev1", "next process")["status"] == "reserved"


def test_file_lab_state_json_writes_use_unique_cleaned_up_temp_files(tmp_path: Path, monkeypatch) -> None:
    state = FileLabState(tmp_path / ".switchfleet_lab")
    observed: list[Path] = []
    original_replace = file_lab_state_module.os.replace

    def capture_replace(source: str | Path, destination: str | Path) -> None:
        observed.append(Path(source))
        original_replace(source, destination)

    monkeypatch.setattr(file_lab_state_module.os, "replace", capture_replace)
    state._write_json(state.paths.dry_runs, {"dry_runs": [{"id": "first"}]})
    state._write_json(state.paths.dry_runs, {"dry_runs": [{"id": "second"}]})

    assert len(observed) == 2
    assert observed[0] != observed[1]
    assert all(not path.exists() for path in observed)


def test_file_lab_state_reports_corrupt_json(tmp_path: Path) -> None:
    state = FileLabState(tmp_path / ".switchfleet_lab")
    state.paths.dry_runs.write_text("{not-json", encoding="utf-8")

    try:
        state.read_dry_runs()
    except FileLabStateError as exc:
        assert "corrupt json" in str(exc).casefold()
    else:
        raise AssertionError("Corrupt file state was not rejected")
