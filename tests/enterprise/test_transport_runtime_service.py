from __future__ import annotations

import pytest

from app.core.exceptions import ConfigApplyNotAllowedError
from app.core.transport_strategy import DeviceFamily, TransportKind
from app.db.models.device import Device
from app.db.session import SessionLocal
from app.services.driver_runtime_service import DriverRuntimeService


def test_driver_runtime_service_decisions_are_deterministic_and_safe() -> None:
    service = DriverRuntimeService()

    first = service.decide(vendor="Cisco", model="Catalyst 2960", platform="ios")
    second = service.decide(vendor="Cisco", model="Catalyst 2960", platform="ios")

    assert first == second
    assert first.selected_transport == TransportKind.netmiko
    assert first.family == DeviceFamily.cisco_ios
    assert first.config_apply_allowed is False
    assert first.real_apply_certified is False
    with pytest.raises(ConfigApplyNotAllowedError):
        service.assert_config_apply_blocked(first)


def test_driver_runtime_summary_counts_and_zero_real_apply_certification() -> None:
    summary = DriverRuntimeService().build_runtime_summary()

    assert summary.total_profiles >= 10
    assert summary.netmiko_profiles >= 6
    assert summary.paramiko_profiles >= 1
    assert summary.custom_cli_profiles >= 2
    assert summary.icmp_only_profiles == 1
    assert summary.unsupported_profiles == 1
    assert summary.config_apply_supported_count >= 1
    assert summary.real_apply_certified_count == 0
    assert summary.config_apply_allowed_globally is False


def test_driver_runtime_service_maps_inventory_device_and_old_driver_name() -> None:
    session = SessionLocal()
    device = Device(
        ip_address="10.90.0.10",
        management_ip="10.90.0.10",
        hostname="sw1",
        vendor="Cisco",
        model="Catalyst 2960",
        platform="ios",
        driver_name="CiscoIOSDriver",
    )
    session.add(device)
    session.commit()

    decision = DriverRuntimeService(session).get_transport_decision_for_device(str(device.id))

    assert decision.device_id == str(device.id)
    assert decision.hostname == "sw1"
    assert decision.driver_name == "CiscoIOSDriver"
    assert decision.family == DeviceFamily.cisco_ios
    assert decision.selected_transport == TransportKind.netmiko
    assert decision.config_apply_allowed is False
