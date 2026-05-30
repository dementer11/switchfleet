from __future__ import annotations

import fnmatch
import builtins
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.lab_validation import LabDriverValidation
from app.repositories import coerce_uuid, optional_uuid


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def comparable_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def normalize_match_value(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def model_matches(pattern: str | None, model: str) -> bool:
    if pattern is None or not pattern.strip():
        return True
    return fnmatch.fnmatch(normalize_match_value(model), normalize_match_value(pattern))


class LabValidationRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        vendor: str,
        driver_name: str,
        capability: str,
        platform: str | None = None,
        model_pattern: str | None = None,
        lab_environment: str | None = None,
        evidence_summary: str | None = None,
        expires_at: datetime | None = None,
    ) -> LabDriverValidation:
        validation = LabDriverValidation(
            vendor=vendor,
            platform=platform,
            model_pattern=model_pattern,
            driver_name=driver_name,
            capability=capability,
            status="pending",
            lab_environment=lab_environment,
            evidence_summary=evidence_summary,
            expires_at=expires_at,
        )
        self.session.add(validation)
        self.session.flush()
        return validation

    def get(self, validation_id: str | uuid.UUID) -> LabDriverValidation:
        parsed_id = coerce_uuid(validation_id, object_name="Lab validation")
        validation = self.session.get(LabDriverValidation, parsed_id)
        if validation is None:
            raise NotFoundError(f"Lab validation {validation_id} not found")
        return validation

    def list(
        self,
        vendor: str | None = None,
        driver_name: str | None = None,
        capability: str | None = None,
        status: str | None = None,
    ) -> builtins.list[LabDriverValidation]:
        statement = select(LabDriverValidation)
        if vendor is not None:
            statement = statement.where(LabDriverValidation.vendor == vendor)
        if driver_name is not None:
            statement = statement.where(LabDriverValidation.driver_name == driver_name)
        if capability is not None:
            statement = statement.where(LabDriverValidation.capability == capability)
        if status is not None:
            statement = statement.where(LabDriverValidation.status == status)
        return list(self.session.scalars(statement.order_by(LabDriverValidation.created_at.desc())).all())

    def find_approved(
        self,
        vendor: str,
        model: str,
        driver_name: str,
        capability: str,
        at: datetime | None = None,
    ) -> LabDriverValidation | None:
        now = at or utcnow()
        for validation in self.list(driver_name=driver_name, capability=capability, status="approved"):
            if normalize_match_value(validation.vendor) != normalize_match_value(vendor):
                continue
            if validation.expires_at is not None and comparable_datetime(validation.expires_at) <= now:
                continue
            if not model_matches(validation.model_pattern, model):
                continue
            return validation
        return None

    def matching_approved_candidates(
        self,
        vendor: str,
        driver_name: str,
        capability: str | None = None,
    ) -> builtins.list[LabDriverValidation]:
        candidates = self.list(driver_name=driver_name, capability=capability, status="approved")
        return [
            validation
            for validation in candidates
            if normalize_match_value(validation.vendor) == normalize_match_value(vendor)
        ]

    def mark_approved(
        self,
        validation_id: str | uuid.UUID,
        validated_by: str,
        evidence_summary: str | None = None,
        expires_at: datetime | None = None,
    ) -> LabDriverValidation:
        validation = self.get(validation_id)
        validation.status = "approved"
        validation.validated_by = validated_by
        validation.validated_at = utcnow()
        validation.expires_at = expires_at if expires_at is not None else validation.expires_at
        if evidence_summary is not None:
            validation.evidence_summary = evidence_summary
        self.session.flush()
        return validation

    def mark_rejected(
        self,
        validation_id: str | uuid.UUID,
        validated_by: str,
        evidence_summary: str | None = None,
    ) -> LabDriverValidation:
        validation = self.get(validation_id)
        validation.status = "rejected"
        validation.validated_by = validated_by
        validation.validated_at = utcnow()
        if evidence_summary is not None:
            validation.evidence_summary = evidence_summary
        self.session.flush()
        return validation

    def mark_expired(self, validation_id: str | uuid.UUID) -> LabDriverValidation:
        validation = self.get(validation_id)
        validation.status = "expired"
        validation.expires_at = utcnow()
        self.session.flush()
        return validation

    def update_transcript(
        self,
        validation_id: str | uuid.UUID,
        transcript_id: str | uuid.UUID | None,
    ) -> LabDriverValidation:
        validation = self.get(validation_id)
        validation.transcript_id = optional_uuid(transcript_id, object_name="Lab validation transcript")
        self.session.flush()
        return validation
