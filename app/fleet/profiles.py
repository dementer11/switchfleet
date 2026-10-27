"""Vendor-aware plans for the current SwitchFleet CLI profiles.

Plans are data only. Password values are deliberately never stored in a plan;
the executor substitutes the documented placeholder immediately before send.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from app.core.transport_strategy import DeviceFamily
from app.core.vendor_driver_contracts import VendorOperation, get_vendor_driver_contract
from app.drivers.base import PortIntent, VlanIntent

PASSWORD_PLACEHOLDER = "__SWITCHFLEET_NEW_PASSWORD__"
_READ_FAMILIES = {"huawei_vrp", "hpe_comware", "hpe_procurve", "cisco_ios", "dell_os", "bulat", "qtech", "eltex", "generic_ssh"}
_TEMPLATE_FAMILIES = {"huawei_vrp", "hpe_comware", "hpe_procurve", "cisco_ios", "dell_os"}
_BLOCKED_FAMILIES = {"unknown", "icmp", "limited_web", "non_switch"}
_FAMILY_DRIVER = {
    "huawei_vrp": ("Huawei", "S5735", "app.drivers.huawei_vrp", "HuaweiVRPDriver"),
    "hpe_comware": ("HPE", "1910", "app.drivers.hp_comware", "HPComwareDriver"),
    "hpe_procurve": ("HPE", "2530", "app.drivers.hpe_procurve", "HPEProCurveDriver"),
    "cisco_ios": ("Cisco", "Catalyst 2960", "app.drivers.cisco_ios", "CiscoIOSDriver"),
    "dell_os": ("Dell", "PowerConnect", "app.drivers.dell_powerconnect", "DellPowerConnectDriver"),
    "bulat": ("Bulat", "BS2500", "app.drivers.bulat_bs", "BulatBSDriver"),
    "qtech": ("QTECH", "QSW-4610", "app.drivers.cisco_ios", "CiscoIOSDriver"),
    "eltex": ("Eltex", "MES2324", "app.drivers.eltex_mes", "EltexMESDriver"),
    "generic_ssh": ("Generic", "GenericSSH", "app.drivers.generic_ssh", "GenericSSHDriver"),
}
_FAMILIES: dict[str, DeviceFamily] = {item.value: item for item in DeviceFamily}


def list_profiles() -> list[dict[str, Any]]:
    """Return safe, non-secret metadata for families accepted by this layer."""
    rows: list[dict[str, Any]] = []
    for family, (vendor, model, _module, _driver) in _FAMILY_DRIVER.items():
        operations = ["facts", "backup", "commands"]
        if family in _TEMPLATE_FAMILIES:
            operations += ["configure", "vlan_create", "vlan_assign_port", "port_description", "port_state", "password_change"]
        rows.append({"family": family, "vendor": vendor, "model_example": model, "operations": operations})
    return rows


def build_device_plan(device: dict[str, Any], operation: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """Build a validated CLI plan without opening a transport."""
    family = str(device.get("family") or "unknown").casefold()
    if family in _BLOCKED_FAMILIES or family not in _READ_FAMILIES:
        return _unsupported_plan(device, operation, f"CLI execution is unsupported for family {family!r}")
    if family == "generic_ssh" and operation != "commands":
        return _unsupported_plan(device, operation, "Generic SSH accepts explicit exec commands only")
    if operation not in {"facts", "backup", "commands", "configure", "vlan_create", "vlan_assign_port", "port_description", "port_state", "password_change"}:
        return _unsupported_plan(device, operation, f"Unknown operation {operation!r}")
    try:
        params = _validate_parameters(parameters)
        plan = _base_plan(device, family, operation)
        contract = get_vendor_driver_contract(_FAMILIES[family])
        plan["backup_setup_commands"] = list(contract.read_only_setup_commands)
        if operation in {"facts", "backup"}:
            if not contract.read_only_commands:
                return _unsupported_plan(device, operation, f"No read-only command profile for {family}")
            plan["commands"] = [_facts_command(family)] if operation == "facts" else list(contract.read_only_commands)
            plan["setup_commands"] = list(contract.read_only_setup_commands)
            plan["requires_backup"] = False
            plan["backup_commands"] = []
            return plan
        if operation == "commands":
            commands = _as_commands(params.get("commands"))
            plan["commands"] = commands
            plan["requires_backup"] = True
            plan["backup_commands"] = list(contract.read_only_commands)
            return plan
        if operation == "configure":
            commands = _as_commands(params.get("commands"))
            plan["commands"] = commands
            plan["requires_backup"] = True
            plan["backup_commands"] = list(contract.read_only_commands)
            return plan
        if family not in _TEMPLATE_FAMILIES:
            return _unsupported_plan(device, operation, f"No confirmed {operation} template for {family}")
        driver = _make_driver(family, str(plan["ip_address"]))
        if operation == "vlan_create":
            vlan_id = _vlan_id(params.get("vlan_id"))
            name = _text(params.get("name", ""), "name", required=False)
            rendered = driver.render_vlan_present(VlanIntent(vlan_id=vlan_id, name=name or None, state="present"))
        elif operation == "vlan_assign_port":
            vlan_id = _vlan_id(params.get("vlan_id"))
            interface = _text(params.get("interface"), "interface")
            rendered = driver.render_access_port(PortIntent(interface=interface, mode="access", access_vlan=vlan_id, allowed_vlans=None, native_vlan=None, description=None, admin_state="up"))
        elif operation == "port_description":
            interface = _text(params.get("interface"), "interface")
            description = _text(params.get("description"), "description")
            rendered = _port_specific_commands(driver, family, interface, description=description)
        elif operation == "port_state":
            interface = _text(params.get("interface"), "interface")
            state = _text(params.get("state", params.get("admin_state")), "state").casefold()
            if state not in {"up", "down"}:
                raise ValueError("state must be 'up' or 'down'")
            port_state: Literal["up", "down"] = "up" if state == "up" else "down"
            rendered = _port_specific_commands(driver, family, interface, state=port_state)
        else:  # password_change
            username = _text(params.get("username"), "username")
            level = int(params.get("level", 1))
            if level < 0 or level > 15:
                raise ValueError("level must be in range 0..15")
            templates = contract.config_command_templates.get(VendorOperation.password_change)
            if not templates:
                return _unsupported_plan(device, operation, f"No confirmed password template for {family}")
            command_params = {"username": username, "level": level, "password": PASSWORD_PLACEHOLDER}
            rendered = [template.format(**command_params) for template in templates]
        setup, commands, saves = _split_setup_save(rendered, contract.save_or_commit_commands)
        if operation != "password_change" and not saves:
            saves = list(contract.save_or_commit_commands)
        if family == "hpe_procurve" and operation in {"vlan_create", "vlan_assign_port", "port_description", "port_state"}:
            setup = ["configure terminal", *setup]
            commands = [*commands, "exit"]
        plan["setup_commands"] = setup
        plan["commands"] = commands
        plan["save_commands"] = saves
        plan["verify_commands"] = _verification_commands(driver, operation, params)
        plan["requires_backup"] = True
        plan["backup_commands"] = list(contract.read_only_commands)
        if not plan["backup_commands"]:
            return _unsupported_plan(device, operation, f"Cannot safely change {family}: backup command is unavailable")
        return plan
    except (TypeError, ValueError, KeyError) as exc:
        return _unsupported_plan(device, operation, str(exc))


def _base_plan(device: dict[str, Any], family: str, operation: str) -> dict[str, Any]:
    ip = str(device.get("ip_address") or "").strip()
    if not ip:
        raise ValueError("ip_address is required")
    port = int(device.get("port", 22))
    if not 1 <= port <= 65535:
        raise ValueError("port must be in range 1..65535")
    return {"device_id": str(device.get("id", "")), "ip_address": ip, "port": port, "label": str(device.get("label") or ip), "family": family, "operation": operation, "commands": [], "setup_commands": [], "save_commands": [], "verify_commands": [], "requires_backup": False, "backup_commands": [], "timeout": 30, "status": "ready", "error": None}


def _unsupported_plan(device: dict[str, Any], operation: str, reason: str) -> dict[str, Any]:
    try:
        port = int(device.get("port", 22) or 22)
        if not 1 <= port <= 65535:
            port = 22
    except (TypeError, ValueError):
        port = 22
    return {"device_id": str(device.get("id", "")), "ip_address": str(device.get("ip_address", "")), "port": port, "label": str(device.get("label") or ""), "family": str(device.get("family") or "unknown").casefold(), "operation": operation, "commands": [], "setup_commands": [], "save_commands": [], "verify_commands": [], "requires_backup": False, "backup_commands": [], "backup_setup_commands": [], "timeout": 30, "status": "unsupported", "error": reason}


def _validate_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(parameters, dict):
        raise TypeError("parameters must be an object")
    for key, value in parameters.items():
        if key != "commands" and isinstance(value, str) and ("\n" in value or "\r" in value):
            raise ValueError(f"parameter {key} must not contain newline")
    return parameters


def _text(value: Any, key: str, required: bool = True) -> str:
    if value is None:
        value = ""
    text = str(value).strip()
    if required and not text:
        raise ValueError(f"{key} is required")
    if re.search(r"[\r\n]", text):
        raise ValueError(f"{key} must not contain newline")
    return text


def _vlan_id(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("vlan_id must be an integer") from exc
    if not 1 <= number <= 4094:
        raise ValueError("vlan_id must be in range 1..4094")
    return number


def _as_commands(value: Any) -> list[str]:
    if isinstance(value, str):
        rows = value.splitlines()
    elif isinstance(value, list):
        rows = value
    else:
        raise TypeError("commands must be a list of CLI lines or multiline string")
    commands = [_text(item, "command") for item in rows]
    if not commands:
        raise ValueError("commands cannot be empty")
    return commands


def _make_driver(family: str, host: str) -> Any:
    import importlib

    _vendor, _model, module, name = _FAMILY_DRIVER[family]
    return getattr(importlib.import_module(module), name)(host)


def _port_specific_commands(
    driver: Any,
    family: str,
    interface: str,
    *,
    description: str | None = None,
    state: Literal["up", "down"] | None = None,
) -> list[str]:
    if family in {"cisco_ios", "dell_os"}:
        begin, end = "configure terminal", "end"
        commands = [begin, f"interface {interface}"]
        if description is not None:
            commands.append(f"description {description}")
        if state is not None:
            commands.append("no shutdown" if state == "up" else "shutdown")
        commands += ["exit", end]
        return commands
    if family in {"huawei_vrp", "hpe_comware"}:
        commands = ["system-view", f"interface {interface}"]
        if description is not None:
            commands.append(f"description {description}")
        if state is not None:
            commands.append("undo shutdown" if state == "up" else "shutdown")
        commands += ["quit", "quit"]
        return commands
    # ProCurve methods expose the exact per-port CLI spellings in this driver.
    # The existing ProCurve renderer requires an access VLAN even though the
    # profile-specific lines selected below are only description/state.
    intent = PortIntent(interface=interface, mode="access", access_vlan=1, allowed_vlans=None, native_vlan=None, description=description, admin_state=state or "up")
    rendered = driver.render_access_port(intent)
    keep = ([f"name {description}"] if description is not None else []) + (["enable" if state == "up" else "disable"] if state is not None else [])
    if not keep:
        raise ValueError("port operation has no commands")
    sections: list[list[str]] = []
    current_context: list[str] | None = None
    for line in rendered:
        if line == f"interface {interface}":
            if current_context is not None:
                sections.append(current_context)
            current_context = [line]
            continue
        if current_context is not None:
            current_context.append(line)
            if line == "exit":
                sections.append(current_context)
                current_context = None
    if current_context:
        sections.append(current_context)
    selected = next((section for section in sections if any(command in section for command in keep)), [])
    return selected


def _split_setup_save(commands: list[str], save_commands: tuple[str, ...]) -> tuple[list[str], list[str], list[str]]:
    setup: list[str] = []
    body: list[str] = []
    saves: list[str] = []
    save_set = set(save_commands)
    for command in commands:
        if command in save_set:
            saves.append(command)
        elif command in {"configure terminal", "system-view", "configure", "aaa"} and not body:
            setup.append(command)
        else:
            body.append(command)
    return setup, body, saves


def _verification_commands(driver: Any, operation: str, parameters: dict[str, Any]) -> list[str]:
    if operation == "vlan_create":
        try:
            return [driver.render_show_vlan_command(_vlan_id(parameters.get("vlan_id")))]
        except NotImplementedError:
            return []
    return []


def _facts_command(family: str) -> str:
    return "display version" if family in {"huawei_vrp", "hpe_comware"} else "show version"
