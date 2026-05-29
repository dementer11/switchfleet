import pytest

from app.utils.vlan_ranges import format_vlan_range, parse_vlan_range


def test_parse_vlan_range() -> None:
    assert parse_vlan_range("10,20-22,21") == [10, 20, 21, 22]


def test_format_vlan_range() -> None:
    assert format_vlan_range([22, 20, 21, 10]) == "10,20-22"


def test_rejects_invalid_vlan() -> None:
    with pytest.raises(ValueError):
        parse_vlan_range("0")

