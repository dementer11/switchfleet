from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DeviceInput(BaseModel):
    hostname: str | None = None
    ip_address: str
    vendor: str = ""
    model: str = ""
    site: str | None = None
    role: str | None = None
    tags: dict[str, Any] = Field(default_factory=dict)


class DeviceImportRequest(BaseModel):
    records: list[DeviceInput]


class DeviceRead(DeviceInput):
    model_config = ConfigDict(from_attributes=True)

    platform: str = ""
    driver_name: str = ""
    status: str = "unknown"
    capabilities: dict[str, Any] = Field(default_factory=dict)

