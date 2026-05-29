from __future__ import annotations


def parse_vlan_range(value: str) -> list[int]:
    vlans: set[int] = set()
    for part in value.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_raw, end_raw = token.split("-", 1)
            start = _parse_vlan_id(start_raw)
            end = _parse_vlan_id(end_raw)
            if start > end:
                raise ValueError(f"Invalid VLAN range {token!r}: start is greater than end")
            vlans.update(range(start, end + 1))
        else:
            vlans.add(_parse_vlan_id(token))
    return sorted(vlans)


def format_vlan_range(vlans: list[int]) -> str:
    ordered = sorted(set(vlans))
    if not ordered:
        return ""
    ranges: list[str] = []
    start = previous = ordered[0]
    for vlan in ordered[1:]:
        if vlan == previous + 1:
            previous = vlan
            continue
        ranges.append(_format_range(start, previous))
        start = previous = vlan
    ranges.append(_format_range(start, previous))
    return ",".join(ranges)


def _parse_vlan_id(value: str) -> int:
    vlan_id = int(value)
    if vlan_id < 1 or vlan_id > 4094:
        raise ValueError(f"VLAN id out of range: {vlan_id}")
    return vlan_id


def _format_range(start: int, end: int) -> str:
    return str(start) if start == end else f"{start}-{end}"

