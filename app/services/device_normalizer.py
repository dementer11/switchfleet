from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass, field
from typing import Any


CANONICAL_FIELD_ALIASES = {
    "ip": "management_ip",
    "ip_address": "management_ip",
    "management ip": "management_ip",
    "management_ip": "management_ip",
    "host": "hostname",
    "hostname": "hostname",
    "name": "hostname",
    "vendor": "vendor",
    "manufacturer": "vendor",
    "model": "model",
    "platform": "platform",
    "site": "site",
    "location": "location",
    "rack": "rack",
    "role": "role",
    "tags": "tags",
    "credential_name": "credential_name",
    "credential": "credential_name",
}


@dataclass(frozen=True)
class NormalizedDeviceRecord:
    valid: bool
    data: dict[str, Any]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def normalize_inventory_record(record: dict[str, Any]) -> NormalizedDeviceRecord:
    canonical = canonicalize_record(record)
    errors: list[str] = []
    warnings: list[str] = []
    management_ip = str(canonical.get("management_ip") or "").strip()
    if not management_ip:
        errors.append("management_ip is required")
    else:
        try:
            canonical["management_ip"] = str(ipaddress.ip_address(management_ip))
            canonical["ip_address"] = canonical["management_ip"]
        except ValueError:
            errors.append(f"Invalid management_ip: {management_ip}")

    vendor = str(canonical.get("vendor") or "").strip()
    model = str(canonical.get("model") or "").strip()
    hostname = str(canonical.get("hostname") or "").strip()
    if not vendor and not model:
        warnings.append("vendor/model are empty; driver resolution will use GenericSSHDriver")
    if not hostname:
        warnings.append("hostname is empty")

    normalized_vendor = normalize_vendor(vendor, model)
    normalized_model = normalize_model(model)
    platform = str(canonical.get("platform") or "").strip() or infer_platform(normalized_vendor, normalized_model)
    tags = normalize_tags(canonical.get("tags"))
    data = {
        "hostname": hostname or None,
        "management_ip": canonical.get("management_ip"),
        "ip_address": canonical.get("ip_address"),
        "vendor": vendor,
        "model": model,
        "normalized_vendor": normalized_vendor,
        "normalized_model": normalized_model,
        "platform": platform,
        "site": empty_to_none(canonical.get("site")),
        "location": empty_to_none(canonical.get("location")),
        "rack": empty_to_none(canonical.get("rack")),
        "role": empty_to_none(canonical.get("role")),
        "tags": tags,
        "credential_name": empty_to_none(canonical.get("credential_name")),
        "warnings": warnings,
    }
    return NormalizedDeviceRecord(valid=not errors, data=data, errors=errors, warnings=warnings)


def canonicalize_record(record: dict[str, Any]) -> dict[str, Any]:
    canonical: dict[str, Any] = {}
    for key, value in record.items():
        normalized_key = str(key).strip().casefold().replace("-", "_")
        normalized_key = " ".join(normalized_key.split())
        target = CANONICAL_FIELD_ALIASES.get(normalized_key) or CANONICAL_FIELD_ALIASES.get(normalized_key.replace("_", " "))
        if target:
            canonical[target] = value
    return canonical


def normalize_vendor(vendor: str, model: str = "") -> str:
    text = f"{vendor} {model}".casefold()
    if "huawei" in text or re.search(r"\b(s57|s67|ce68|s17|s23|s24)\d*", text):
        return "Huawei"
    if "bulat" in text or "bs2500" in text or "bs6300" in text:
        return "Bulat"
    if "eltex" in text or "mes2324" in text or "mes2348" in text or "mes2448" in text:
        return "Eltex"
    if "qsw" in text or "qtech" in text:
        return "QSW"
    if "3com" in text:
        return "3Com"
    if "hpe" in text or re.search(r"\bhp\b", text):
        return "HPE"
    if "dell" in text or "powerconnect" in text:
        return "Dell"
    if "cisco" in text or "cat2960" in text or "catalyst" in text:
        return "Cisco"
    if "d-link" in text or "des1100" in text:
        return "D-Link"
    if "continent" in text:
        return "Continent"
    if "icmp" in text:
        return "ICMP"
    if "unknown snmp" in text:
        return "Unknown SNMP"
    return vendor.strip() or "Unknown"


def normalize_model(model: str) -> str:
    collapsed = " ".join(str(model or "").strip().split())
    replacements = {
        "cisco cat2960": "Cat2960",
        "powerconnect 3524": "PowerConnect 3524",
    }
    lowered = collapsed.casefold()
    for needle, replacement in replacements.items():
        if needle in lowered:
            return replacement
    return collapsed


def infer_platform(normalized_vendor: str, normalized_model: str) -> str:
    text = f"{normalized_vendor} {normalized_model}".casefold()
    if normalized_vendor == "Huawei":
        return "vrp"
    if any(token in text for token in ("hpe 1910", "hpe 1920", "hpe 5130", "3com s4210", "3com s5500")):
        return "comware"
    if any(token in text for token in ("hpe 2510", "hpe 2530")):
        return "procurve"
    if normalized_vendor == "Cisco":
        return "ios"
    if normalized_vendor == "Dell":
        return "powerconnect"
    if normalized_vendor == "Bulat":
        return "bulat-bs"
    if normalized_vendor == "Eltex":
        return "eltex-mes"
    if normalized_vendor == "ICMP":
        return "icmp-only"
    if normalized_vendor in {"Unknown", "Unknown SNMP"}:
        return "unknown"
    return normalized_vendor.casefold().replace(" ", "-")


def normalize_tags(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return sorted({str(item).strip() for item in value if str(item).strip()})
    if isinstance(value, dict):
        labels = value.get("labels", [])
        return normalize_tags(labels)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
                return normalize_tags(parsed)
            except json.JSONDecodeError:
                pass
        return sorted({part.strip() for part in re.split(r"[,;]", stripped) if part.strip()})
    return [str(value)]


def empty_to_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
