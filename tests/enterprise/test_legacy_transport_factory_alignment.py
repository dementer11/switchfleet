from __future__ import annotations

import pytest

from netops_orchestrator.drivers.registry import driver_for
from netops_orchestrator.models import Device, VlanChange
from netops_orchestrator.runtime_compat import LegacyRuntimeSafetyError
from netops_orchestrator.transports.factory import selected_transport_label, transport_for_plan
from netops_orchestrator.transports.netmiko_ssh import NetmikoCliTransport
from netops_orchestrator.transports.ssh_paramiko import ParamikoCliTransport, SshCredentials


def device(vendor: str, model: str) -> Device:
    return Device(label="sw1", ip_address="10.0.0.1", vendor=vendor, model=model)


CREDS = SshCredentials(username="netops", password="secret")


def test_transport_factory_auto_follows_runtime_decision_for_read_only_backup() -> None:
    cisco_plan = driver_for(device("Cisco", "Catalyst 2960")).backup_config()
    bulat_plan = driver_for(device("Bulat", "BS2500-48G4S-A")).backup_config()

    cisco_transport = transport_for_plan(cisco_plan, CREDS, preference="auto")
    bulat_transport = transport_for_plan(bulat_plan, CREDS, preference="auto")

    assert isinstance(cisco_transport, NetmikoCliTransport)
    assert cisco_transport.device_type == "cisco_ios"
    assert selected_transport_label(cisco_plan) == "netmiko:cisco_ios"
    assert isinstance(bulat_transport, ParamikoCliTransport)
    assert selected_transport_label(bulat_plan) == "paramiko"


def test_transport_factory_preferences_cannot_bypass_unsupported_or_icmp() -> None:
    unsupported_plan = driver_for(device("Huawei", "Unknown Product")).backup_config()
    icmp_plan = driver_for(device("ICMP-only", "ICMP-only")).backup_config()

    for plan in (unsupported_plan, icmp_plan):
        with pytest.raises(LegacyRuntimeSafetyError):
            transport_for_plan(plan, CREDS, preference="auto")
        with pytest.raises(LegacyRuntimeSafetyError):
            transport_for_plan(plan, CREDS, preference="paramiko")
        with pytest.raises(LegacyRuntimeSafetyError):
            transport_for_plan(plan, CREDS, preference="netmiko")


def test_transport_factory_forced_netmiko_cannot_bypass_custom_cli_strategy() -> None:
    plan = driver_for(device("Bulat", "BS2500-48G4S-A")).backup_config()

    with pytest.raises(ValueError, match="no Netmiko device_type"):
        transport_for_plan(plan, CREDS, preference="netmiko")


def test_transport_factory_blocks_config_operation_before_transport_instantiation(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_constructor(*args: object, **kwargs: object) -> object:
        raise AssertionError("Transport must not be instantiated for blocked apply")

    monkeypatch.setattr("netops_orchestrator.transports.factory.NetmikoCliTransport", fail_constructor)
    monkeypatch.setattr("netops_orchestrator.transports.factory.ParamikoCliTransport", fail_constructor)
    plan = driver_for(device("Cisco", "Catalyst 2960")).configure_vlan(VlanChange(vlan_id=120, name="CAMERAS"))

    with pytest.raises(LegacyRuntimeSafetyError, match="Legacy CLI real apply is disabled"):
        transport_for_plan(plan, CREDS, preference="auto")


def test_transport_factory_qtech_backup_is_read_only_but_config_is_blocked() -> None:
    backup_plan = driver_for(device("QTECH", "QSW-4610-52T-AC")).backup_config()
    config_plan = driver_for(device("QTECH", "QSW-4610-52T-AC")).configure_vlan(VlanChange(vlan_id=120))

    assert isinstance(transport_for_plan(backup_plan, CREDS), ParamikoCliTransport)
    with pytest.raises(LegacyRuntimeSafetyError):
        transport_for_plan(config_plan, CREDS)
