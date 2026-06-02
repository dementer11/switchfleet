from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CredentialSecretCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    username: str
    secret: str = Field(min_length=1)
    auth_type: str = "password"
    purpose: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CredentialSecretUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    username: str | None = None
    purpose: str | None = None
    metadata: dict[str, Any] | None = None


class CredentialSecretRotate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: str = Field(min_length=1)


class CredentialSecretRead(BaseModel):
    id: str
    name: str
    username: str
    auth_type: str
    purpose: str | None = None
    version: int
    active: bool
    has_secret: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None
    updated_by: str | None = None
    created_at: str
    updated_at: str
    rotated_at: str | None = None
    disabled_at: str | None = None


class CredentialSecretUseCheck(BaseModel):
    id: str
    usable: bool
    reasons: list[str] = Field(default_factory=list)

