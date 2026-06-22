from __future__ import annotations

import re

MASK = "<redacted>"

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?P<prefix>\bpassword\s+(?:irreversible-cipher|cipher|simple|0|plaintext)?\s*)(?P<secret>\S+)", re.I),
    re.compile(r"(?P<prefix>\bsecret\s+)(?P<secret>\S+)", re.I),
    re.compile(r"(?P<prefix>\benable\s+secret\s+)(?P<secret>\S+)", re.I),
    re.compile(r"(?P<prefix>\bcommunity\s+)(?P<secret>\S+)", re.I),
    re.compile(r"(?P<prefix>\btoken\s+)(?P<secret>\S+)", re.I),
    re.compile(r"(?P<prefix>\bapi[_-]?key\s+)(?P<secret>\S+)", re.I),
    re.compile(r"(?P<prefix>\bauthorization\s+(?:bearer\s+)?)(?P<secret>\S+)", re.I),
    re.compile(r"(?P<prefix>\bprivate[_-]?key\s+)(?P<secret>\S+)", re.I),
)


def mask_secret_value(value: str | None) -> str | None:
    if value is None:
        return None
    return MASK if value else value


def mask_secrets(text: str, explicit_secrets: list[str] | tuple[str, ...] = ()) -> str:
    masked = text
    for secret in explicit_secrets:
        if secret:
            masked = masked.replace(secret, MASK)
    for pattern in SECRET_PATTERNS:
        masked = pattern.sub(lambda match: f"{match.group('prefix')}{MASK}", masked)
    return masked


def mask_command_list(commands: list[str], explicit_secrets: list[str] | tuple[str, ...] = ()) -> list[str]:
    return [mask_secrets(command, explicit_secrets=explicit_secrets) for command in commands]
