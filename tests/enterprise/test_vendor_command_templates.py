import pytest

from app.core.exceptions import ConfigApplyNotAllowedError, SafetyError
from app.core.transport_strategy import DeviceFamily
from app.core.vendor_driver_contracts import VendorOperation
from app.services.vendor_command_templates import VendorCommandTemplateService, command_hash, private_command_hash


def test_vendor_templates_render_secret_commands_as_secret_and_redacted() -> None:
    service = VendorCommandTemplateService()

    commands = service.render(
        DeviceFamily.cisco_ios,
        VendorOperation.password_change,
        {"username": "admin", "password": "VerySecret", "level": 15},
    )

    assert any(command.secret for command in commands)
    assert "VerySecret" in "\n".join(command.command for command in commands)
    assert "VerySecret" not in "\n".join(command.to_safe_dict()["command"] for command in commands)
    assert command_hash(commands)


def test_secret_command_public_hash_is_redacted_but_private_hash_binds_secret() -> None:
    service = VendorCommandTemplateService()
    first = service.render(
        DeviceFamily.cisco_ios,
        VendorOperation.password_change,
        {"username": "admin", "password": "FirstSecret", "level": 15},
    )
    second = service.render(
        DeviceFamily.cisco_ios,
        VendorOperation.password_change,
        {"username": "admin", "password": "SecondSecret", "level": 15},
    )

    assert command_hash(first) == command_hash(second)
    assert private_command_hash(first, secret_key="excel-lab-secret-key") != private_command_hash(second, secret_key="excel-lab-secret-key")


def test_vendor_templates_deny_invalid_inputs_and_uncertain_vendors() -> None:
    service = VendorCommandTemplateService()

    with pytest.raises(SafetyError):
        service.render(DeviceFamily.cisco_ios, VendorOperation.vlan_create, {"vlan_id": 4095, "name": "BAD"})
    with pytest.raises(SafetyError):
        service.render(
            DeviceFamily.cisco_ios,
            VendorOperation.password_change,
            {"username": "admin", "password": "VerySecret\nwrite memory", "level": 15},
        )
    with pytest.raises(SafetyError):
        service.render(
            DeviceFamily.cisco_ios,
            VendorOperation.password_change,
            {"username": "admin", "password": "VerySecret", "level": "15\nwrite memory"},
        )
    with pytest.raises(ConfigApplyNotAllowedError):
        service.render(DeviceFamily.eltex, VendorOperation.vlan_create, {"vlan_id": 120, "name": "CAMERAS"})
    with pytest.raises(ConfigApplyNotAllowedError):
        service.render(DeviceFamily.unknown, VendorOperation.password_change, {"username": "admin", "password": "x", "level": 15})


def test_command_plan_must_match_vendor_template() -> None:
    service = VendorCommandTemplateService()
    params = {"vlan_id": 120, "name": "CAMERAS"}
    rendered = service.render(DeviceFamily.cisco_ios, VendorOperation.vlan_create, params)

    assert service.validate_command_plan(DeviceFamily.cisco_ios, VendorOperation.vlan_create, params, rendered) == []
    tampered = [{"command": "configure terminal"}, {"command": "erase startup-config"}]
    assert service.validate_command_plan(DeviceFamily.cisco_ios, VendorOperation.vlan_create, params, tampered)


def test_dell_save_template_is_allowed_for_lab_candidate() -> None:
    service = VendorCommandTemplateService()

    commands = service.render(DeviceFamily.dell_os, VendorOperation.vlan_create, {"vlan_id": 120, "name": "CAMERAS"})

    assert commands[-1].command == "copy running-config startup-config"
