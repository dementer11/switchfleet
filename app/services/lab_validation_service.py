from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import SafetyError
from app.db.models.lab_validation import LabDriverValidation, LabValidationChecklistItem, LabValidationTranscript
from app.db.session import SessionLocal
from app.repositories.lab_validation_checklists import LabValidationChecklistRepository
from app.repositories.lab_validation_transcripts import LabValidationTranscriptRepository
from app.repositories.lab_validations import LabValidationRepository, comparable_datetime, model_matches
from app.schemas.lab_validation import (
    LabChecklistItemRead,
    LabTranscriptCreateRequest,
    LabTranscriptRead,
    LabValidationApproveRequest,
    LabValidationCreateRequest,
    LabValidationListResponse,
    LabValidationRead,
    LabValidationRejectRequest,
)
from app.utils.transcript_sanitizer import sanitize_transcript


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LabValidationService:
    def __init__(
        self,
        session: Session | None = None,
        settings: Settings | None = None,
    ):
        self.session = session or SessionLocal()
        self.settings = settings or get_settings()
        self.validations = LabValidationRepository(self.session)
        self.transcripts = LabValidationTranscriptRepository(self.session)
        self.checklists = LabValidationChecklistRepository(self.session)

    def create_validation_request(self, payload: LabValidationCreateRequest, actor: str) -> LabValidationRead:
        validation = self.validations.create(
            vendor=payload.vendor,
            platform=payload.platform,
            model_pattern=payload.model_pattern,
            driver_name=payload.driver_name,
            capability=payload.capability,
            lab_environment=payload.lab_environment,
            evidence_summary=payload.evidence_summary,
            expires_at=payload.expires_at,
        )
        self.checklists.create_items(str(validation.id), self.build_default_checklist(payload.capability))
        self.session.flush()
        return self._read_validation(validation)

    def attach_sanitized_transcript(
        self,
        validation_id: str,
        payload: LabTranscriptCreateRequest,
    ) -> LabTranscriptRead:
        self.validations.get(validation_id)
        sanitized = sanitize_transcript(payload.raw_text)
        transcript = self.transcripts.create_sanitized_transcript(
            validation_id=validation_id,
            filename=payload.filename,
            content_type=payload.content_type,
            sanitized_text=sanitized.sanitized_text,
            sha256=sanitized.sha256,
        )
        self.validations.update_transcript(validation_id, transcript.id)
        self.session.flush()
        return self._read_transcript(transcript)

    def approve_validation(
        self,
        validation_id: str,
        payload: LabValidationApproveRequest,
        actor: str,
    ) -> LabValidationRead:
        validation = self.validations.mark_approved(
            validation_id,
            validated_by=actor,
            evidence_summary=payload.evidence_summary,
            expires_at=payload.expires_at,
        )
        return self._read_validation(validation)

    def reject_validation(
        self,
        validation_id: str,
        payload: LabValidationRejectRequest,
        actor: str,
    ) -> LabValidationRead:
        validation = self.validations.mark_rejected(
            validation_id,
            validated_by=actor,
            evidence_summary=payload.evidence_summary,
        )
        return self._read_validation(validation)

    def expire_validation(self, validation_id: str) -> LabValidationRead:
        return self._read_validation(self.validations.mark_expired(validation_id))

    def list_validations(
        self,
        vendor: str | None = None,
        driver_name: str | None = None,
        capability: str | None = None,
        status: str | None = None,
    ) -> LabValidationListResponse:
        return LabValidationListResponse(
            items=[
                self._read_validation(validation, include_children=False)
                for validation in self.validations.list(
                    vendor=vendor,
                    driver_name=driver_name,
                    capability=capability,
                    status=status,
                )
            ]
        )

    def get_validation(self, validation_id: str) -> LabValidationRead:
        return self._read_validation(self.validations.get(validation_id))

    def get_checklist(self, validation_id: str) -> list[LabChecklistItemRead]:
        self.validations.get(validation_id)
        return [self._read_checklist_item(item) for item in self.checklists.list_for_validation(validation_id)]

    def update_checklist_item(self, validation_id: str, item_id: str, status: str, notes: str | None = None) -> LabChecklistItemRead:
        self.validations.get(validation_id)
        item = self.checklists.get(item_id)
        if str(item.validation_id) != validation_id:
            raise SafetyError("Checklist item does not belong to this lab validation")
        item = self.checklists.update_item_status(item_id, status=status, notes=notes)
        return self._read_checklist_item(item)

    def build_default_checklist(self, capability: str) -> list[tuple[str, str]]:
        if capability == "password_change":
            return [
                ("connect_lab_device", "Connect to lab device"),
                ("verify_current_credential", "Verify current credential works"),
                ("render_masked_plan", "Render masked command plan"),
                ("apply_password_lab", "Apply password change in isolated lab"),
                ("verify_new_credential", "Verify new credential works"),
                ("verify_old_credential", "Verify old credential no longer works, if safe"),
                ("save_after_verification", "Save config only after verification"),
                ("reboot_reconnect_check", "Run reboot/reconnect check, if lab permits"),
                ("confirm_transcript_sanitized", "Confirm transcript sanitized"),
                ("document_rollback", "Confirm rollback procedure documented"),
            ]
        if capability == "vlan_change":
            return [
                ("connect_lab_device", "Connect to lab device"),
                ("create_vlan", "Create VLAN"),
                ("assign_test_port", "Assign VLAN to test port"),
                ("verify_running_config", "Verify running config"),
                ("verify_idempotent_rerun", "Verify idempotent re-run"),
                ("rollback_vlan", "Rollback VLAN"),
                ("confirm_transcript_sanitized", "Confirm transcript sanitized"),
            ]
        return [
            ("connect", "Connect"),
            ("dry_run", "Dry-run"),
            ("apply_lab", "Apply in lab"),
            ("verify", "Verify"),
            ("rollback", "Rollback"),
            ("sanitize_transcript", "Sanitize transcript"),
        ]

    def assert_real_apply_allowed(
        self,
        vendor: str,
        model: str,
        driver_name: str,
        capability: str,
    ) -> None:
        if not self.settings.allow_real_device_apply:
            raise SafetyError("Real device apply is disabled by NCP_ALLOW_REAL_DEVICE_APPLY=false")

        approved = self.validations.find_approved(
            vendor=vendor,
            model=model,
            driver_name=driver_name,
            capability=capability,
        )
        if approved is not None:
            return

        now = utcnow()
        candidates = self.validations.matching_approved_candidates(vendor=vendor, driver_name=driver_name)
        if not candidates:
            raise SafetyError("No approved lab validation exists for this vendor and driver")
        capability_candidates = [item for item in candidates if item.capability == capability]
        if not capability_candidates:
            raise SafetyError(f"Capability {capability!r} is not lab validated for driver {driver_name!r}")
        non_expired = [
            item
            for item in capability_candidates
            if item.expires_at is None or comparable_datetime(item.expires_at) > now
        ]
        if not non_expired:
            raise SafetyError("Approved lab validation is expired")
        if not any(model_matches(item.model_pattern, model) for item in non_expired):
            raise SafetyError("No approved lab validation matches this device model")
        raise SafetyError("No approved lab validation found for destructive real apply")

    def _read_validation(self, validation: LabDriverValidation, include_children: bool = True) -> LabValidationRead:
        transcripts: list[LabTranscriptRead] = []
        checklist: list[LabChecklistItemRead] = []
        if include_children:
            transcripts = [self._read_transcript(item) for item in self.transcripts.list_for_validation(validation.id)]
            checklist = [self._read_checklist_item(item) for item in self.checklists.list_for_validation(validation.id)]
        return LabValidationRead(
            id=str(validation.id),
            vendor=validation.vendor,
            platform=validation.platform,
            model_pattern=validation.model_pattern,
            driver_name=validation.driver_name,
            capability=validation.capability,
            status=validation.status,
            validated_by=validation.validated_by,
            validated_at=validation.validated_at.isoformat() if validation.validated_at else None,
            expires_at=validation.expires_at.isoformat() if validation.expires_at else None,
            lab_environment=validation.lab_environment,
            evidence_summary=validation.evidence_summary,
            transcript_id=str(validation.transcript_id) if validation.transcript_id else None,
            created_at=validation.created_at.isoformat(),
            updated_at=validation.updated_at.isoformat(),
            transcripts=transcripts,
            checklist=checklist,
        )

    def _read_transcript(self, transcript: LabValidationTranscript) -> LabTranscriptRead:
        preview = transcript.sanitized_text[:500]
        return LabTranscriptRead(
            id=str(transcript.id),
            validation_id=str(transcript.validation_id) if transcript.validation_id else None,
            filename=transcript.filename,
            content_type=transcript.content_type,
            sha256=transcript.sha256,
            created_at=transcript.created_at.isoformat(),
            sanitized_preview=preview,
        )

    def _read_checklist_item(self, item: LabValidationChecklistItem) -> LabChecklistItemRead:
        return LabChecklistItemRead(
            id=str(item.id),
            validation_id=str(item.validation_id),
            item_key=item.item_key,
            description=item.description,
            status=item.status,
            notes=item.notes,
            created_at=item.created_at.isoformat(),
            updated_at=item.updated_at.isoformat(),
        )
