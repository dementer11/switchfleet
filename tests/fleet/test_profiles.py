from __future__ import annotations

from app.fleet.profiles import PASSWORD_PLACEHOLDER, build_device_plan, list_profiles


def device(family: str = "cisco_ios") -> dict:
    return {"id": "sw-1", "label": "edge", "ip_address": "192.0.2.10", "vendor": "Cisco", "model": "Catalyst 2960", "family": family}


def test_profile_list_exposes_supported_templates_and_read_only_profiles() -> None:
    profiles = {row["family"]: row for row in list_profiles()}
    assert "vlan_create" in profiles["cisco_ios"]["operations"]
    assert "vlan_create" not in profiles["eltex"]["operations"]
    assert "commands" in profiles["generic_ssh"]["operations"]


def test_password_plan_only_contains_placeholder_and_marks_backup() -> None:
    plan = build_device_plan(device(), "password_change", {"username": "operator", "level": 15})
    assert plan["status"] == "ready"
    assert plan["requires_backup"] is True
    assert plan["backup_commands"] == ["show running-config"]
    assert plan["save_commands"] == ["write memory"]
    assert PASSWORD_PLACEHOLDER in "\n".join(plan["commands"])
    assert "not-the-secret" not in str(build_device_plan(device(), "password_change", {"username": "operator", "new_password": "not-the-secret"}))


def test_supported_vlan_plan_uses_existing_driver_commands_and_save() -> None:
    plan = build_device_plan(device("hpe_comware"), "vlan_create", {"vlan_id": 42, "name": "USERS"})
    assert plan["status"] == "ready"
    assert plan["requires_backup"] is True
    assert plan["setup_commands"] == ["system-view"]
    assert plan["commands"] == ["vlan 42", "name USERS", "quit", "quit"]
    assert plan["save_commands"] == ["save force"]
    assert plan["verify_commands"] == ["display vlan 42"]


def test_custom_cli_families_do_not_get_invented_standard_templates() -> None:
    for family in ("bulat", "qtech", "eltex"):
        plan = build_device_plan(device(family), "vlan_create", {"vlan_id": 10, "name": "LAB"})
        assert plan["status"] == "unsupported"
        custom = build_device_plan(device(family), "configure", {"commands": ["configure terminal", "end"]})
        assert custom["status"] == "ready"
        assert custom["requires_backup"] is True


def test_generic_ssh_allows_only_explicit_commands_and_blocks_unknown_families() -> None:
    allowed = build_device_plan(device("generic_ssh"), "commands", {"commands": ["show version"]})
    denied = build_device_plan(device("generic_ssh"), "configure", {"commands": ["configure terminal"]})
    blocked = build_device_plan(device("unknown"), "facts", {})
    assert allowed["status"] == "ready" and allowed["requires_backup"]
    assert allowed["backup_commands"] == ["show running-config"]
    assert denied["status"] == "unsupported"
    assert blocked["status"] == "unsupported"


def test_parameters_reject_newline_and_vlan_out_of_range() -> None:
    newline = build_device_plan(device(), "vlan_create", {"vlan_id": 10, "name": "x\nwrite erase"})
    bad_vlan = build_device_plan(device(), "vlan_create", {"vlan_id": 4095, "name": "x"})
    assert newline["status"] == "unsupported"
    assert bad_vlan["status"] == "unsupported"


def test_facts_uses_version_commands_not_running_config() -> None:
    for family, command in (("huawei_vrp", "display version"), ("hpe_comware", "display version"), ("cisco_ios", "show version"), ("dell_os", "show version")):
        plan = build_device_plan(device(family), "facts", {})
        assert plan["commands"] == [command]
        assert plan["backup_commands"] == []
        assert plan["requires_backup"] is False


def test_commands_multiline_string_splits_but_command_list_lines_stay_single() -> None:
    multiline = build_device_plan(device(), "commands", {"commands": "show version\nshow clock"})
    embedded_newline = build_device_plan(device(), "commands", {"commands": ["show version\nreload"]})
    assert multiline["status"] == "ready"
    assert multiline["commands"] == ["show version", "show clock"]
    assert embedded_newline["status"] == "unsupported"


def test_port_state_accepts_state_and_admin_state_aliases() -> None:
    state = build_device_plan(device(), "port_state", {"interface": "Gi1/0/1", "state": "down"})
    admin_state = build_device_plan(device(), "port_state", {"interface": "Gi1/0/1", "admin_state": "down"})
    assert state["status"] == admin_state["status"] == "ready"
    assert state["commands"] == admin_state["commands"]


def test_procurve_mutation_templates_enter_and_leave_config_mode() -> None:
    vlan = build_device_plan(device("hpe_procurve"), "vlan_create", {"vlan_id": 50, "name": "LAB"})
    port_state = build_device_plan(device("hpe_procurve"), "port_state", {"interface": "1", "admin_state": "down"})
    custom = build_device_plan(device("hpe_procurve"), "configure", {"commands": ["vlan 50", "name LAB"]})
    assert vlan["setup_commands"] == ["configure terminal"]
    assert vlan["commands"][-1] == "exit"
    assert vlan["save_commands"] == ["write memory"]
    assert port_state["setup_commands"] == ["configure terminal"]
    assert port_state["commands"] == ["interface 1", "disable", "exit", "exit"]
    assert custom["setup_commands"] == []
    assert custom["commands"] == ["vlan 50", "name LAB"]
