from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class VlanIntentSchema(BaseModel):
    vlan_id: int = Field(ge=1, le=4094)
    name: str | None = Field(default=None, max_length=64)
    state: Literal["present", "absent"] = "present"
    force: bool = False

