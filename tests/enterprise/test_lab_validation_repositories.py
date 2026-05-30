from __future__ import annotations

from datetime import timedelta

from app.db.session import SessionLocal
from app.repositories.lab_validation_checklists import LabValidationChecklistRepository
from app.repositories.lab_validation_transcripts import LabValidationTranscriptRepository
from app.repositories.lab_validations import LabValidationRepository
from app.services.runtime_state import utcnow


def test_lab_validation_repository_state_transitions_and_lookup() -> None:
    session = SessionLocal()
    validations = LabValidationRepository(session)
    validation = validations.create(
        vendor="Cisco",
        model_pattern="Cat2960*",
        driver_name="CiscoIOSDriver",
        capability="password_change",
    )

    assert validation.status == "pending"
    assert validations.find_approved("cisco", "Cat2960-48", "CiscoIOSDriver", "password_change") is None

    approved = validations.mark_approved(validation.id, validated_by="sec")

    assert approved.status == "approved"
    assert validations.find_approved("cisco", "Cat2960-48", "CiscoIOSDriver", "password_change") is not None
    assert validations.find_approved("cisco", "ISR4331", "CiscoIOSDriver", "password_change") is None
    assert validations.find_approved("cisco", "Cat2960-48", "HuaweiVRPDriver", "password_change") is None
    assert validations.find_approved("cisco", "Cat2960-48", "CiscoIOSDriver", "vlan_change") is None

    validations.mark_expired(validation.id)
    assert validations.find_approved("cisco", "Cat2960-48", "CiscoIOSDriver", "password_change") is None


def test_lab_validation_model_pattern_exact_wildcard_and_empty_patterns() -> None:
    session = SessionLocal()
    validations = LabValidationRepository(session)
    exact = validations.create(
        vendor="Huawei",
        model_pattern="S5735-L48T4X-A1",
        driver_name="HuaweiVRPDriver",
        capability="vlan_change",
    )
    wildcard = validations.create(
        vendor="Huawei",
        model_pattern="S5735*",
        driver_name="HuaweiVRPDriver",
        capability="password_change",
    )
    generic = validations.create(
        vendor="Huawei",
        driver_name="HuaweiVRPDriver",
        capability="config_backup",
    )
    validations.mark_approved(exact.id, validated_by="sec")
    validations.mark_approved(wildcard.id, validated_by="sec")
    validations.mark_approved(generic.id, validated_by="sec")

    assert validations.find_approved("huawei", "S5735-L48T4X-A1", "HuaweiVRPDriver", "vlan_change") is not None
    assert validations.find_approved("huawei", "S5735-S24T4X", "HuaweiVRPDriver", "password_change") is not None
    assert validations.find_approved("huawei", "S6720-54C-EI-48S-AC", "HuaweiVRPDriver", "config_backup") is not None
    assert validations.find_approved("huawei", "S5735-S24T4X", "HuaweiVRPDriver", "vlan_change") is None


def test_lab_validation_repository_reject_and_expiration_filter() -> None:
    session = SessionLocal()
    validations = LabValidationRepository(session)
    rejected = validations.create(vendor="Huawei", driver_name="HuaweiVRPDriver", capability="vlan_change")
    validations.mark_rejected(rejected.id, validated_by="sec", evidence_summary="syntax mismatch")
    expired = validations.create(
        vendor="Huawei",
        driver_name="HuaweiVRPDriver",
        capability="vlan_change",
        expires_at=utcnow() - timedelta(days=1),
    )
    validations.mark_approved(expired.id, validated_by="sec")

    assert validations.get(rejected.id).status == "rejected"
    assert validations.find_approved("Huawei", "S5735", "HuaweiVRPDriver", "vlan_change") is None


def test_transcript_and_checklist_repositories() -> None:
    session = SessionLocal()
    validations = LabValidationRepository(session)
    transcripts = LabValidationTranscriptRepository(session)
    checklists = LabValidationChecklistRepository(session)
    validation = validations.create(vendor="Cisco", driver_name="CiscoIOSDriver", capability="vlan_change")

    transcript = transcripts.create_sanitized_transcript(
        validation_id=validation.id,
        filename="session.txt",
        content_type="text/plain",
        sanitized_text="password <redacted>",
        sha256="a" * 64,
    )
    validations.update_transcript(validation.id, transcript.id)
    items = checklists.create_items(str(validation.id), [("connect", "Connect"), ("verify", "Verify")])
    updated = checklists.update_item_status(items[0].id, status="passed", notes="ok")

    assert transcripts.get(transcript.id).filename == "session.txt"
    assert {item.item_key for item in checklists.list_for_validation(validation.id)} == {"connect", "verify"}
    assert updated.status == "passed"
    assert validations.get(validation.id).transcript_id == transcript.id
