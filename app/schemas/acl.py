from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AclRuleSchema(BaseModel):
    sequence: int = Field(ge=1)
    action: Literal["permit", "deny"]
    protocol: Literal["ip", "tcp", "udp", "icmp"]
    src: str
    src_port: str | None = None
    dst: str
    dst_port: str | None = None
    remark: str | None = None


class AclDefinitionSchema(BaseModel):
    name: str
    acl_type: Literal["standard", "extended", "ipv4", "ipv6"]
    rules: list[AclRuleSchema]

