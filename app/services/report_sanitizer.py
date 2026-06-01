from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.utils.masking import MASK, mask_secrets

SAFE_EXACT_KEYS = (
    "credential_status",
    "credential_summary",
    "invalid_credentials",
    "password_change",
    "password_changes",
    "password_rollout",
    "password_rollouts",
    "valid_credentials",
    "workflow_counts_by_type",
    "workflow_summary",
)

SAFE_COMPACT_KEYS = (
    "passwordchange",
    "passwordchanges",
    "passwordrollout",
    "passwordrollouts",
)

SECRET_EXACT_KEYS = (
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "backup_content",
    "candidate_config",
    "command_output",
    "config_text",
    "credential",
    "credentials",
    "pass",
    "passwd",
    "password",
    "private_key",
    "raw_config",
    "running_config",
    "secret",
    "startup_config",
    "token",
)

SECRET_COMPACT_KEYS = (
    "apikey",
    "backupcontent",
    "candidateconfig",
    "commandoutput",
    "configtext",
    "privatekey",
    "rawconfig",
    "runningconfig",
    "startupconfig",
)


def _key_tokens(key: str) -> set[str]:
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    return {token for token in re.split(r"[^a-z0-9]+", separated.casefold()) if token}


def _is_secret_key(key: str) -> bool:
    normalized = key.casefold()
    compact = re.sub(r"[^a-z0-9]+", "", normalized)
    if normalized in SAFE_EXACT_KEYS:
        return False
    if compact in SAFE_COMPACT_KEYS:
        return False
    if normalized in SECRET_EXACT_KEYS:
        return True
    if compact in SECRET_COMPACT_KEYS:
        return True
    tokens = _key_tokens(key)
    if tokens & {"pass", "passwd", "password", "secret", "token"}:
        return True
    if {"api", "key"}.issubset(tokens) or "apikey" in tokens:
        return True
    if {"private", "key"}.issubset(tokens) or "privatekey" in tokens:
        return True
    if "config" in tokens and (tokens & {"raw", "text", "running", "startup", "candidate"}):
        return True
    if {"command", "output"}.issubset(tokens):
        return True
    if "backup" in tokens and (tokens & {"content", "config", "raw"}):
        return True
    if "credential" in tokens and (tokens & {"password", "secret", "token", "material", "encrypted", "private"}):
        return True
    if (tokens & {"auth", "authorization"}) and (tokens & {"password", "secret", "token", "key", "material", "header"}):
        return True
    return False


def sanitize_export_value(value: Any, key: str | None = None) -> Any:
    if key is not None and _is_secret_key(key):
        return MASK
    if isinstance(value, Mapping):
        return sanitize_report_metadata(value)
    if isinstance(value, list):
        return [sanitize_export_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_export_value(item) for item in value]
    if isinstance(value, str):
        return mask_secrets(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return mask_secrets(str(value))


def sanitize_report_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key in sorted((metadata or {}).keys(), key=str):
        str_key = str(key)
        sanitized[str_key] = sanitize_export_value((metadata or {})[key], key=str_key)
    return sanitized


def sanitize_audit_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    return sanitize_report_metadata(metadata)


def sanitize_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): sanitize_export_value(value, key=str(key)) for key, value in sorted(record.items(), key=lambda item: str(item[0]))}


def sanitize_sequence(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [sanitize_record(record) for record in records]
