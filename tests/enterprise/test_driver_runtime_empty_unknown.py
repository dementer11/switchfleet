from __future__ import annotations

from app.core.transport_strategy import DeviceFamily, TransportKind
from app.services.driver_runtime_service import DriverRuntimeService


def test_driver_runtime_empty_summary_is_stable_without_devices() -> None:
    summary = DriverRuntimeService().build_runtime_summary()
    safety = DriverRuntimeService().build_safety_report()

    assert summary.total_profiles > 0
    assert summary.real_apply_certified_count == 0
    assert summary.config_apply_allowed_globally is False
    assert safety.real_apply_enabled is False
    assert safety.session_opening_from_api is False


def test_unknown_vendor_selects_unsupported_runtime() -> None:
    decision = DriverRuntimeService().decide(vendor="NoSuchVendor", model="NoSuchModel")

    assert decision.family == DeviceFamily.unknown
    assert decision.selected_transport == TransportKind.unsupported
    assert decision.read_only_allowed is False
    assert decision.config_apply_allowed is False
    assert decision.unsupported_reason
