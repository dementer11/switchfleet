from __future__ import annotations

from app.db.models.device import Device
from app.db.session import SessionLocal
from app.services.driver_runtime_service import DriverRuntimeService
from app.services.observability_service import ObservabilityService
from app.services.operator_console_service import OperatorConsoleService
from tests.enterprise.operator_console_helpers import seed_operator_console


def test_existing_inventory_devices_map_to_runtime_decisions_without_workflow_changes() -> None:
    session = SessionLocal()
    ids = seed_operator_console(session)
    service = DriverRuntimeService(session)

    decision = service.get_transport_decision_for_device(ids["device_id"])
    dashboard = OperatorConsoleService(session).get_dashboard()
    readiness = ObservabilityService(session).get_device_readiness_report()

    assert decision.driver_name == "CiscoIOSDriver"
    assert decision.config_apply_allowed is False
    assert dashboard.health.total_devices >= 1
    assert readiness.total >= 1


def test_old_driver_names_map_or_fail_safely() -> None:
    session = SessionLocal()
    known = Device(
        ip_address="192.0.2.10",
        vendor="Huawei",
        model="S5735",
        platform="vrp",
        driver_name="HuaweiVRPDriver",
    )
    unknown = Device(
        ip_address="192.0.2.11",
        vendor="Mystery",
        model="MysteryBox",
        platform="",
        driver_name="",
    )
    session.add_all([known, unknown])
    session.commit()
    service = DriverRuntimeService(session)

    known_decision = service.get_transport_decision_for_device(str(known.id))
    unknown_decision = service.get_transport_decision_for_device(str(unknown.id))

    assert known_decision.driver_name == "HuaweiVRPDriver"
    assert known_decision.selected_transport.value == "netmiko"
    assert known_decision.config_apply_allowed is False
    assert unknown_decision.selected_transport.value == "unsupported"
    assert unknown_decision.unsupported_reason
