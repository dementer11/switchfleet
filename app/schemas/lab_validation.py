from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ValidationCapability = Literal["vlan_change", "password_change", "acl_change", "port_change", "config_backup"]
ValidationStatus = Literal["pending", "approved", "rejected", "expired"]
ChecklistStatus = Literal["pending", "passed", "failed", "skipped"]


class LabValidationCreateRequest(BaseModel):
    vendor: str = Field(min_length=1)
    platform: str | None = None
    model_pattern: str | None = None
    driver_name: str = Field(min_length=1)
    capability: ValidationCapability
    lab_environment: str | None = None
    evidence_summary: str | None = None
    expires_at: datetime | None = None


class LabTranscriptCreateRequest(BaseModel):
    filename: str = Field(min_length=1)
    content_type: str = Field(default="text/plain", min_length=1)
    raw_text: str = Field(min_length=1)


class LabValidationApproveRequest(BaseModel):
    evidence_summary: str | None = None
    expires_at: datetime | None = None


class LabValidationRejectRequest(BaseModel):
    evidence_summary: str | None = None


class LabChecklistItemUpdateRequest(BaseModel):
    status: ChecklistStatus
    notes: str | None = None


class LabTranscriptRead(BaseModel):
    id: str
    validation_id: str | None = None
    filename: str
    content_type: str
    sha256: str
    created_at: str
    sanitized_preview: str


class LabChecklistItemRead(BaseModel):
    id: str
    validation_id: str
    item_key: str
    description: str
    status: str
    notes: str | None = None
    created_at: str
    updated_at: str


class LabValidationRead(BaseModel):
    id: str
    vendor: str
    platform: str | None = None
    model_pattern: str | None = None
    driver_name: str
    capability: str
    status: str
    validated_by: str | None = None
    validated_at: str | None = None
    expires_at: str | None = None
    lab_environment: str | None = None
    evidence_summary: str | None = None
    transcript_id: str | None = None
    created_at: str
    updated_at: str
    transcripts: list[LabTranscriptRead] = Field(default_factory=list)
    checklist: list[LabChecklistItemRead] = Field(default_factory=list)


class LabValidationListResponse(BaseModel):
    items: list[LabValidationRead]

