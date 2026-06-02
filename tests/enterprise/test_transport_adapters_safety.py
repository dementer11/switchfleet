from __future__ import annotations

import pytest

from app.core.exceptions import ConfigApplyNotAllowedError, RealApplyDisabledError
from app.core.transport_strategy import TransportKind
from app.services.driver_capability_matrix import DriverCapabilityMatrix
from app.services.transport_runtime import (
    CustomCliTransportAdapter,
    IcmpTransportAdapter,
    NetmikoTransportAdapter,
    ParamikoTransportAdapter,
    RuntimeCredentials,
    TransportRuntime,
    UnsupportedTransportAdapter,
)


@pytest.mark.parametrize(
    "adapter_class",
    [NetmikoTransportAdapter, ParamikoTransportAdapter, CustomCliTransportAdapter, IcmpTransportAdapter],
)
def test_transport_adapters_block_config_changing_methods(adapter_class: type[NetmikoTransportAdapter]) -> None:
    decision = DriverCapabilityMatrix().decide(vendor="Cisco", model="Catalyst 2960")
    adapter = adapter_class(decision, RuntimeCredentials(username="admin", password="SHOULD_NOT_LEAK"))

    with pytest.raises(ConfigApplyNotAllowedError):
        adapter.enter_config_mode()
    with pytest.raises(ConfigApplyNotAllowedError):
        adapter.stage_config(["vlan 100"])
    with pytest.raises(ConfigApplyNotAllowedError):
        adapter.commit_or_save()
    with pytest.raises(ConfigApplyNotAllowedError):
        adapter.rollback_prepare()
    assert "SHOULD_NOT_LEAK" not in repr(adapter)
    assert "SHOULD_NOT_LEAK" not in repr(adapter.credentials)


def test_runtime_create_session_never_enables_config_apply() -> None:
    runtime = TransportRuntime()
    decision = DriverCapabilityMatrix().decide(vendor="Cisco", model="Catalyst 2960")

    session = runtime.create_session(decision, RuntimeCredentials(username="admin"), mode="read_only")

    assert isinstance(session, NetmikoTransportAdapter)
    assert runtime.supports_read_only(decision) is True
    assert runtime.supports_config_staging(decision) is False
    with pytest.raises(ConfigApplyNotAllowedError):
        runtime.create_session(decision, RuntimeCredentials(username="admin"), mode="config")


def test_icmp_and_unsupported_adapters_fail_closed() -> None:
    matrix = DriverCapabilityMatrix()
    runtime = TransportRuntime(matrix)
    icmp_decision = matrix.decide(vendor="ICMP", model="ICMP-only")
    unknown_decision = matrix.decide(vendor="Mystery", model="Unknown")

    icmp = runtime.create_session(icmp_decision)
    unsupported = runtime.create_session(unknown_decision)

    assert isinstance(icmp, IcmpTransportAdapter)
    assert icmp.decision.selected_transport == TransportKind.icmp_only
    with pytest.raises(ConfigApplyNotAllowedError):
        icmp.run_show("show version")
    assert isinstance(unsupported, UnsupportedTransportAdapter)
    with pytest.raises(RealApplyDisabledError):
        unsupported.connect()
