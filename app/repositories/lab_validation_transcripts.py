from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.lab_validation import LabValidationTranscript
from app.repositories import coerce_uuid, optional_uuid


class LabValidationTranscriptRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_sanitized_transcript(
        self,
        filename: str,
        content_type: str,
        sanitized_text: str,
        sha256: str,
        validation_id: str | uuid.UUID | None = None,
    ) -> LabValidationTranscript:
        transcript = LabValidationTranscript(
            validation_id=optional_uuid(validation_id, object_name="Lab validation"),
            filename=filename,
            content_type=content_type,
            sanitized_text=sanitized_text,
            sha256=sha256,
        )
        self.session.add(transcript)
        self.session.flush()
        return transcript

    def get(self, transcript_id: str | uuid.UUID) -> LabValidationTranscript:
        parsed_id = coerce_uuid(transcript_id, object_name="Lab validation transcript")
        transcript = self.session.get(LabValidationTranscript, parsed_id)
        if transcript is None:
            raise NotFoundError(f"Lab validation transcript {transcript_id} not found")
        return transcript

    def list_for_validation(self, validation_id: str | uuid.UUID) -> list[LabValidationTranscript]:
        parsed_id = coerce_uuid(validation_id, object_name="Lab validation")
        return list(
            self.session.scalars(
                select(LabValidationTranscript)
                .where(LabValidationTranscript.validation_id == parsed_id)
                .order_by(LabValidationTranscript.created_at.desc())
            ).all()
        )

