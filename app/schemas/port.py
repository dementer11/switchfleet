from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PortIntentSchema(BaseModel):
    interface: str = Field(min_length=1, max_length=128)
    mode: Literal["access", "trunk"]
    access_vlan: int | None = Field(default=None, ge=1, le=4094)
    allowed_vlans: list[int] | None = None
    native_vlan: int | None = Field(default=None, ge=1, le=4094)
    description: str | None = Field(default=None, max_length=240)
    admin_state: Literal["up", "down"] = "up"

