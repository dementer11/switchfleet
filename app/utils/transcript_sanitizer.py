from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


MASK = "<redacted>"
PRIVATE_KEY_MASK = "-----BEGIN PRIVATE KEY-----\n<redacted>\n-----END PRIVATE KEY-----"

PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)

SECRET_LINE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?P<prefix>\busername\s+\S+\s+password\s+)(?P<secret>\S+)", re.IGNORECASE),
    re.compile(r"(?P<prefix>\busername\s+\S+\s+secret\s+)(?P<secret>\S+)", re.IGNORECASE),
    re.compile(r"(?P<prefix>\bset\s+authentication\s+password\s+)(?P<secret>\S+)", re.IGNORECASE),
    re.compile(r"(?P<prefix>\bsnmp-server\s+community\s+)(?P<secret>\S+)", re.IGNORECASE),
    re.compile(r"(?P<prefix>\b(?:snmp\s+)?community\s+)(?P<secret>\S+)", re.IGNORECASE),
    re.compile(r"(?P<prefix>\bauthorization:\s*bearer\s+)(?P<secret>\S+)", re.IGNORECASE),
    re.compile(r"(?P<prefix>\bauthorization\s+bearer\s+)(?P<secret>\S+)", re.IGNORECASE),
    re.compile(r"(?P<prefix>\benable\s+password\s+)(?P<secret>\S+)", re.IGNORECASE),
    re.compile(r"(?P<prefix>\benable\s+secret\s+)(?P<secret>\S+)", re.IGNORECASE),
    re.compile(r"(?P<prefix>\bpassword\s+(?:irreversible-cipher|cipher|simple|0|plaintext)?\s*)(?P<secret>\S+)", re.IGNORECASE),
    re.compile(r"(?P<prefix>\bpasswd\s+)(?P<secret>\S+)", re.IGNORECASE),
    re.compile(r"(?P<prefix>\bsecret\s+)(?P<secret>\S+)", re.IGNORECASE),
    re.compile(r"(?P<prefix>\btoken\s+)(?P<secret>\S+)", re.IGNORECASE),
)


@dataclass(frozen=True)
class SanitizedTranscript:
    sanitized_text: str
    sha256: str


def sanitize_transcript(raw_text: str) -> SanitizedTranscript:
    sanitized = PRIVATE_KEY_PATTERN.sub(PRIVATE_KEY_MASK, raw_text)
    for pattern in SECRET_LINE_PATTERNS:
        sanitized = pattern.sub(lambda match: f"{match.group('prefix')}{MASK}", sanitized)
    digest = hashlib.sha256(sanitized.encode("utf-8")).hexdigest()
    return SanitizedTranscript(sanitized_text=sanitized, sha256=digest)

