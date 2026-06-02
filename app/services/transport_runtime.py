from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any, NoReturn, Protocol

from app.core.exceptions import ConfigApplyNotAllowedError, RealApplyDisabledError
from app.core.transport_strategy import DriverCapability, TransportDecision, TransportKind
from app.services.driver_capability_matrix import DriverCapabilityMatrix


@dataclass(frozen=True)
class RuntimeCredentials:
    username: str
    password: str | None = None
    enable_password: str | None = None

    def __repr__(self) -> str:
        return "RuntimeCredentials(username={!r}, password=<redacted>, enable_password=<redacted>)".format(self.username)


class TransportSession(Protocol):
    decision: TransportDecision

    def connect(self) -> None:
        ...

    def close(self) -> None:
        ...

    def detect_prompt(self) -> str | None:
        ...

    def run_show(self, command: str) -> str:
        ...

    def enter_privileged_mode(self) -> None:
        ...

    def enter_config_mode(self) -> None:
        ...

    def stage_config(self, commands: list[str]) -> None:
        ...

    def commit_or_save(self) -> None:
        ...

    def rollback_prepare(self) -> str:
        ...

    def get_capabilities(self) -> frozenset[DriverCapability]:
        ...


class BaseTransportAdapter:
    adapter_name = "base"

    def __init__(self, decision: TransportDecision, credentials: RuntimeCredentials | None = None):
        self.decision = decision
        self.credentials = credentials
        self.connected = False

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(transport={self.decision.selected_transport.value!r}, driver={self.decision.driver_name!r})"

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.connected = False

    def detect_prompt(self) -> str | None:
        self._block_real_session("prompt detection")

    def run_show(self, command: str) -> str:
        self._block_real_session(f"read-only command {command!r}")

    def enter_privileged_mode(self) -> None:
        self._block_config_operation("enter privileged mode")

    def enter_config_mode(self) -> None:
        self._block_config_operation("enter config mode")

    def stage_config(self, commands: list[str]) -> None:
        self._block_config_operation(f"stage config commands count={len(commands)}")

    def commit_or_save(self) -> None:
        self._block_config_operation("commit or save")

    def rollback_prepare(self) -> str:
        self._block_config_operation("rollback preparation")

    def get_capabilities(self) -> frozenset[DriverCapability]:
        return self.decision.capabilities

    def optional_dependency_available(self) -> bool:
        return True

    def _block_real_session(self, action: str) -> NoReturn:
        raise RealApplyDisabledError(f"{self.adapter_name} {action} is not executed by the safety-only runtime")

    def _block_config_operation(self, action: str) -> NoReturn:
        raise ConfigApplyNotAllowedError(f"{self.adapter_name} config-changing operation blocked: {action}")


class NetmikoTransportAdapter(BaseTransportAdapter):
    adapter_name = "netmiko"

    def optional_dependency_available(self) -> bool:
        return importlib.util.find_spec("netmiko") is not None

    @property
    def device_type(self) -> str:
        mapping = {
            "CiscoIOSDriver": "cisco_ios",
            "CiscoNXOSDriver": "cisco_nxos",
            "CiscoASADriver": "cisco_asa",
            "HuaweiVRPDriver": "huawei_vrp",
            "HPComwareDriver": "hp_comware",
            "HPEProCurveDriver": "hp_procurve",
            "DellPowerConnectDriver": "dell_powerconnect",
        }
        return mapping.get(self.decision.driver_name, self.decision.family.value)


class ParamikoTransportAdapter(BaseTransportAdapter):
    adapter_name = "paramiko"

    def optional_dependency_available(self) -> bool:
        return importlib.util.find_spec("paramiko") is not None


class CustomCliTransportAdapter(BaseTransportAdapter):
    adapter_name = "custom_cli"


class IcmpTransportAdapter(BaseTransportAdapter):
    adapter_name = "icmp_only"

    def run_show(self, command: str) -> str:
        self._block_config_operation("CLI command on ICMP-only device")


class UnsupportedTransportAdapter(BaseTransportAdapter):
    adapter_name = "unsupported"

    def connect(self) -> None:
        raise RealApplyDisabledError(self.decision.unsupported_reason or "Unsupported runtime profile cannot open sessions")

    def get_capabilities(self) -> frozenset[DriverCapability]:
        return frozenset()


class TransportRuntime:
    def __init__(self, matrix: DriverCapabilityMatrix | None = None):
        self.matrix = matrix or DriverCapabilityMatrix()

    def decide_transport(self, device: Any) -> TransportDecision:
        return self.matrix.decide(
            vendor=str(getattr(device, "vendor", "") or ""),
            model=str(getattr(device, "model", "") or ""),
            platform=str(getattr(device, "platform", "") or ""),
            driver_name=str(getattr(device, "driver_name", "") or "") or None,
            device_id=str(getattr(device, "id", "") or "") or None,
            hostname=getattr(device, "hostname", None),
        )

    def create_session(
        self,
        decision: TransportDecision,
        credentials: RuntimeCredentials | None = None,
        mode: str = "read_only",
    ) -> TransportSession:
        if mode != "read_only":
            self.assert_config_apply_blocked(decision)
        adapter_class = self._adapter_class(decision.selected_transport)
        return adapter_class(decision, credentials)

    def supports_read_only(self, decision: TransportDecision) -> bool:
        return decision.read_only_allowed and DriverCapability.read_only in decision.capabilities

    def supports_config_staging(self, decision: TransportDecision) -> bool:
        return DriverCapability.config_staging in decision.capabilities and decision.config_apply_allowed

    def assert_config_apply_blocked(self, decision: TransportDecision) -> None:
        raise ConfigApplyNotAllowedError(
            f"Config apply is blocked for {decision.driver_name}; config_apply_allowed={decision.config_apply_allowed}, "
            f"real_apply_certified={decision.real_apply_certified}"
        )

    def _adapter_class(self, kind: TransportKind) -> type[BaseTransportAdapter]:
        return {
            TransportKind.netmiko: NetmikoTransportAdapter,
            TransportKind.paramiko: ParamikoTransportAdapter,
            TransportKind.custom_cli: CustomCliTransportAdapter,
            TransportKind.icmp_only: IcmpTransportAdapter,
            TransportKind.unsupported: UnsupportedTransportAdapter,
        }[kind]
