from __future__ import annotations

from app.db.base import Base
from app.db.models.lab_validation import LabDriverValidation, LabValidationChecklistItem, LabValidationTranscript


def test_lab_validation_tables_are_registered() -> None:
    assert "lab_driver_validations" in Base.metadata.tables
    assert "lab_validation_transcripts" in Base.metadata.tables
    assert "lab_validation_checklists" in Base.metadata.tables
    assert LabDriverValidation.__tablename__ == "lab_driver_validations"
    assert LabValidationTranscript.__tablename__ == "lab_validation_transcripts"
    assert LabValidationChecklistItem.__tablename__ == "lab_validation_checklists"


def test_lab_validation_required_columns_exist() -> None:
    validation_columns = Base.metadata.tables["lab_driver_validations"].columns
    transcript_columns = Base.metadata.tables["lab_validation_transcripts"].columns
    checklist_columns = Base.metadata.tables["lab_validation_checklists"].columns

    for column_name in ["vendor", "driver_name", "capability", "status", "created_at", "updated_at"]:
        assert column_name in validation_columns
    for column_name in ["filename", "content_type", "sanitized_text", "sha256", "created_at"]:
        assert column_name in transcript_columns
    for column_name in ["validation_id", "item_key", "description", "status", "created_at", "updated_at"]:
        assert column_name in checklist_columns

