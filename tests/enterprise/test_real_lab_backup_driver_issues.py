from __future__ import annotations

import pytest

from app.core.exceptions import ConfigApplyNotAllowedError
from app.core.transport_strategy import DeviceFamily, DriverCapability, TransportDecision, TransportKind
from app.core.vendor_driver_contracts import VendorOperation, get_vendor_driver_contract
from app.drivers.eltex_mes import EltexMESDriver
from app.services.real_lab_apply_runner import (
    build_transport_diagnostic,
    legacy_ssh_options_for_decision,
    output_has_paging_marker,
    prompt_regex_for_decision,
)
from app.services.vendor_command_templates import VendorCommandTemplateService


def _decision(
    family: DeviceFamily,
    *,
    driver_name: str,
    transport: TransportKind = TransportKind.custom_cli,
    fallback: TransportKind | None = TransportKind.paramiko,
) -> TransportDecision:
    return TransportDecision(
        vendor=family.value,
        family=family,
        selected_transport=transport,
        fallback_transport=fallback,
        driver_name=driver_name,
        capabilities=frozenset({DriverCapability.read_only}),
        read_only_allowed=True,
        config_apply_allowed=False,
        real_apply_certified=False,
    )


def test_prompt_regex_accepts_real_lab_prompt_shapes() -> None:
    comware = _decision(DeviceFamily.hpe_comware, driver_name="HPComwareDriver", transport=TransportKind.netmiko)
    eltex = _decision(DeviceFamily.eltex, driver_name="EltexMESDriver")
    qtech = _decision(DeviceFamily.qtech, driver_name="QtechQswDriver")

    prompt_examples = (
        "<169-4-408-0.176>",
        "169-05-501-0.164#",
        "SW-ELTEX-01#",
        "MES2448B#",
        "QSW-4610>",
        "core.switch.local#",
        "switch_01#",
        "ELTEX-MES(standby)#",
        "<Huawei>",
        "[Huawei]",
    )
    for prompt in prompt_examples:
        assert prompt_regex_for_decision(qtech).search(f"show running-config\n{prompt}")

    assert prompt_regex_for_decision(comware).search("display current-configuration\n<169-4-408-0.176>")
    assert prompt_regex_for_decision(eltex).search("show running-config\n169-05-501-0.164#")


def test_prompt_regex_does_not_match_intermediate_config_line_as_prompt() -> None:
    qtech = _decision(DeviceFamily.qtech, driver_name="QtechQswDriver")
    prompt = prompt_regex_for_decision(qtech)

    assert prompt.search("banner motd #\ninterface ethernet 1/0/1\n") is None
    assert prompt.search("banner motd #\ninterface ethernet 1/0/1\nQSW-4610#")


def test_legacy_ssh_options_are_limited_to_legacy_read_only_profiles() -> None:
    qtech = _decision(DeviceFamily.qtech, driver_name="QtechQswDriver")
    eltex = _decision(DeviceFamily.eltex, driver_name="EltexMESDriver")
    comware = _decision(DeviceFamily.hpe_comware, driver_name="HPComwareDriver", transport=TransportKind.netmiko)
    cisco = _decision(DeviceFamily.cisco_ios, driver_name="CiscoIOSDriver", transport=TransportKind.netmiko)
    huawei = _decision(DeviceFamily.huawei_vrp, driver_name="HuaweiVRPDriver", transport=TransportKind.netmiko)

    for decision in (qtech, eltex, comware):
        options = legacy_ssh_options_for_decision(decision)
        assert options is not None
        assert "diffie-hellman-group1-sha1" in options.kex
        assert "ssh-rsa" in options.key_types
        assert "3des-cbc" in options.ciphers

    assert legacy_ssh_options_for_decision(cisco) is None
    assert legacy_ssh_options_for_decision(huawei) is None


def test_paging_markers_are_detected_case_insensitively() -> None:
    assert output_has_paging_marker("line\n---- More ----")
    assert output_has_paging_marker("line\n--More--")
    assert output_has_paging_marker("line\nMore:")
    assert output_has_paging_marker("line\n<--- More --->")
    assert output_has_paging_marker("Press any key to continue")
    assert output_has_paging_marker("press ENTER to continue")
    assert output_has_paging_marker("\n More \n")


def test_transport_diagnostic_redacts_secret_like_text() -> None:
    decision = _decision(DeviceFamily.eltex, driver_name="EltexMESDriver")
    diagnostic = build_transport_diagnostic(
        decision,
        "prompt",
        "password SHOULD_NOT_LEAK while connecting to 192.0.2.44",
        output="username admin secret ALSO_SHOULD_NOT_LEAK\n192.0.2.44\n169-05-501-0.164#",
    )

    assert "SHOULD_NOT_LEAK" not in diagnostic
    assert "ALSO_SHOULD_NOT_LEAK" not in diagnostic
    assert "192.0.2.44" not in diagnostic
    assert "<redacted-ip>" in diagnostic
    assert "phase=prompt" in diagnostic
    assert "family=eltex" in diagnostic
    assert "transport=custom_cli" in diagnostic
    assert "driver=EltexMESDriver" in diagnostic


def test_qtech_and_eltex_config_apply_templates_remain_blocked() -> None:
    service = VendorCommandTemplateService()

    for family in (DeviceFamily.qtech, DeviceFamily.eltex):
        with pytest.raises(ConfigApplyNotAllowedError):
            service.render(family, VendorOperation.vlan_create, {"vlan_id": 123, "name": "TEST"})


def test_eltex_and_qtech_backup_contracts_are_explicit_not_cisco_aliases() -> None:
    eltex_contract = get_vendor_driver_contract(DeviceFamily.eltex)
    qtech_contract = get_vendor_driver_contract(DeviceFamily.qtech)

    assert eltex_contract.read_only_setup_commands == ("terminal datadump",)
    assert eltex_contract.read_only_commands == ("show running-config",)
    assert eltex_contract.apply_support_level.value == "read_only_only"
    assert qtech_contract.read_only_setup_commands == ("terminal length 0",)
    assert qtech_contract.read_only_commands == ("show running-config",)
    assert qtech_contract.apply_support_level.value == "read_only_only"


def test_eltex_app_driver_overrides_cisco_save_behavior_for_backup_profile() -> None:
    driver = EltexMESDriver("192.0.2.44")
    capabilities = driver.capabilities()

    assert driver.running_config_command() == "show running-config"
    assert driver.save_commands() == []
    assert driver.read_only_setup_commands == ("terminal datadump",)
    assert capabilities.command_syntax_family == "eltex_mes"
    assert capabilities.supports_save_config is False
    assert capabilities.destructive_apply_confirmed is False
