from __future__ import annotations

from pathlib import Path

from app.services.file_lab_state import FileLabState


def test_excel_lab_certification_records_are_lab_only(tmp_path: Path) -> None:
    state = FileLabState(tmp_path / ".switchfleet_lab")
    record = state.save_lab_validation(
        {
            "device_id": "dev1",
            "device_label": "sw1-lab",
            "capability": "backup",
            "production_certified": False,
            "evidence": "manual lab check",
        }
    )

    assert record["status"] == "approved"
    assert record["production_certified"] is False
    assert state.latest_validation_for("dev1", "backup") is not None
