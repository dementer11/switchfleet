from __future__ import annotations

from pydantic import BaseModel, Field


class CredentialCreate(BaseModel):
    name: str
    username: str
    password: str = Field(min_length=1)
    enable_password: str | None = None


class CredentialRead(BaseModel):
    id: str
    name: str
    username: str
    auth_type: str = "password"
    has_enable_password: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class CredentialCreated(CredentialRead):
    password: str = "<redacted>"
    enable_password: str | None = None
