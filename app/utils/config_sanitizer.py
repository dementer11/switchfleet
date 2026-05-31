from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field


REDACTION = "<redacted>"


@dataclass(frozen=True)
class SanitizedConfig:
    text: str
    redaction_types: list[str] = field(default_factory=list)
    config_hash: str = ""


def sanitize_config(config_text: str) -> SanitizedConfig:
    sanitized = str(config_text)
    redactions: set[str] = set()

    block_patterns = [
        ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.I | re.S)),
        ("ssh_key_block", re.compile(r"(?m)^.*(?:ssh-rsa|ssh-ed25519|ecdsa-sha2-nistp\d+)\s+[A-Za-z0-9+/=]+.*$")),
    ]
    for label, pattern in block_patterns:
        sanitized, count = pattern.subn(REDACTION, sanitized)
        if count:
            redactions.add(label)

    line_patterns = [
        ("enable_secret", re.compile(r"(?im)^(\s*enable\s+secret(?:\s+\d+)?\s+).+$")),
        ("username_secret", re.compile(r"(?im)^(\s*username\s+\S+.*?\s+secret(?:\s+\d+)?\s+).+$")),
        ("username_password", re.compile(r"(?im)^(\s*username\s+\S+.*?\s+password(?:\s+\d+)?\s+).+$")),
        ("snmp_server_community", re.compile(r"(?im)^(\s*snmp-server\s+community\s+)\S+(.*)$")),
        ("snmp_community", re.compile(r"(?im)^(\s*snmp\s+community\s+)\S+(.*)$")),
        ("tacacs_key", re.compile(r"(?im)^(\s*tacacs-server\s+key(?:\s+\d+)?\s+).+$")),
        ("radius_key", re.compile(r"(?im)^(\s*radius-server\s+key(?:\s+\d+)?\s+).+$")),
        ("ntp_authentication_key", re.compile(r"(?im)^(\s*ntp\s+authentication-key\s+\S+\s+\S+\s+).+$")),
        ("api_token", re.compile(r"(?im)^(\s*(?:api[-_ ]?token|token)\s*[:=]\s*)\S+.*$")),
        ("bearer_token", re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")),
        ("generic_secret", re.compile(r"(?im)^(\s*secret\s+).+$")),
        ("generic_password", re.compile(r"(?im)^(\s*password\s+).+$")),
    ]
    for label, pattern in line_patterns:
        if label in {"snmp_server_community", "snmp_community"}:
            sanitized, count = pattern.subn(rf"\1{REDACTION}\2", sanitized)
        else:
            sanitized, count = pattern.subn(rf"\1{REDACTION}", sanitized)
        if count:
            redactions.add(label)

    return SanitizedConfig(
        text=sanitized,
        redaction_types=sorted(redactions),
        config_hash=hashlib.sha256(sanitized.encode("utf-8")).hexdigest(),
    )
