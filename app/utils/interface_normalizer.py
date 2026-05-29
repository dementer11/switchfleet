from __future__ import annotations


INTERFACE_ALIASES = {
    "gi": "GigabitEthernet",
    "ge": "GigabitEthernet",
    "te": "TenGigabitEthernet",
    "xge": "XGigabitEthernet",
    "eth": "Ethernet",
}


def normalize_interface_name(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("Interface name is empty")
    lower = stripped.lower()
    for alias, expanded in INTERFACE_ALIASES.items():
        if lower.startswith(alias) and len(stripped) > len(alias) and stripped[len(alias)].isdigit():
            return f"{expanded}{stripped[len(alias):]}"
    return stripped

