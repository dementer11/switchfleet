from __future__ import annotations

import socket
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from app.core.exceptions import SafetyError
from app.core.transport_strategy import TransportDecision, TransportKind
from app.core.vendor_driver_contracts import get_vendor_driver_contract
from app.schemas.lab_apply import ApplySafetyDecisionRead
from app.schemas.lab_apply import LabApplyCommand
from app.services.transport_runtime import RuntimeCredentials
from app.services.vendor_command_templates import RenderedCommand
from app.transports.base import CommandExecutionResult
from app.transports.netmiko_transport import NetmikoConnectionParams, NetmikoTransport
from app.utils.masking import mask_secrets


@dataclass(frozen=True)
class LabCommandResult:
    command: str
    output: str
    success: bool
    error: str | None = None
    secret: bool = False


@dataclass(frozen=True)
class RealLabApplyResult:
    executed: bool
    transport_kind: str
    command_count: int
    commands: list[LabApplyCommand]
    outputs: list[LabCommandResult] = field(default_factory=list)
    failed: bool = False
    error: str | None = None


class LabCommandTransport(Protocol):
    def open(self) -> None:
        ...

    def close(self) -> None:
        ...

    def run_command(self, command: str, timeout_seconds: int = 60) -> CommandExecutionResult:
        ...


class RuntimeDevice(Protocol):
    @property
    def management_ip(self) -> Any | None:
        ...

    @property
    def ip_address(self) -> Any:
        ...


class RuntimeApplyEvaluation(Protocol):
    @property
    def decision(self) -> ApplySafetyDecisionRead:
        ...

    @property
    def device(self) -> Any | None:
        ...

    @property
    def transport_decision(self) -> TransportDecision | None:
        ...

    @property
    def internal_commands(self) -> list[RenderedCommand]:
        ...


class NetmikoCommandTransport:
    def __init__(self, decision: TransportDecision, credentials: RuntimeCredentials, host: str, port: int, timeout: int):
        self._transport = NetmikoTransport(
            NetmikoConnectionParams(
                host=host,
                device_type=_netmiko_device_type(decision),
                username=credentials.username,
                password=credentials.password or "",
                enable_password=credentials.enable_password,
                port=port,
                timeout=timeout,
            )
        )

    def open(self) -> None:
        self._transport.open()

    def close(self) -> None:
        self._transport.close()

    def run_command(self, command: str, timeout_seconds: int = 60) -> CommandExecutionResult:
        return self._transport.send_command(command, timeout_seconds=timeout_seconds)


class ParamikoCommandTransport:
    def __init__(self, credentials: RuntimeCredentials, host: str, port: int, timeout: int):
        self.credentials = credentials
        self.host = host
        self.port = port
        self.timeout = timeout
        self._client: object | None = None
        self._channel: object | None = None

    def open(self) -> None:
        try:
            import paramiko  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError("Paramiko is required for lab SSH execution") from exc
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            self.host,
            port=self.port,
            username=self.credentials.username,
            password=self.credentials.password,
            look_for_keys=False,
            allow_agent=False,
            timeout=self.timeout,
        )
        channel = client.invoke_shell(width=200, height=80)
        channel.settimeout(self.timeout)
        self._client = client
        self._channel = channel
        self._read_until_prompt()

    def close(self) -> None:
        if self._channel is not None:
            self._channel.close()  # type: ignore[attr-defined]
        if self._client is not None:
            self._client.close()  # type: ignore[attr-defined]
        self._channel = None
        self._client = None

    def run_command(self, command: str, timeout_seconds: int = 60) -> CommandExecutionResult:
        if self._channel is None:
            raise RuntimeError("Paramiko lab transport is not open")
        self._channel.send(command + "\n")  # type: ignore[attr-defined]
        output, completed = self._read_until_prompt(timeout_seconds)
        return CommandExecutionResult(
            command=command,
            output=output,
            success=completed,
            error=None if completed else f"Timed out waiting for prompt after {timeout_seconds}s",
        )

    def _read_until_prompt(self, timeout_seconds: int | None = None) -> tuple[str, bool]:
        if self._channel is None:
            raise RuntimeError("Paramiko lab transport is not open")
        deadline = time.monotonic() + float(timeout_seconds or self.timeout)
        chunks: list[str] = []
        prompt = re.compile(r"[>#\]]\s*$")
        while time.monotonic() < deadline:
            try:
                if self._channel.recv_ready():  # type: ignore[attr-defined]
                    data = self._channel.recv(65535).decode("utf-8", errors="replace")  # type: ignore[attr-defined]
                    chunks.append(data)
                    if prompt.search("".join(chunks)):
                        return "".join(chunks), True
                else:
                    time.sleep(0.05)
            except socket.timeout:
                break
        return "".join(chunks), False


LabTransportBuilder = Callable[[TransportDecision, RuntimeCredentials, str, int, int], LabCommandTransport]


class LabSshTransportFactory:
    def create(
        self,
        decision: TransportDecision,
        credentials: RuntimeCredentials,
        host: str,
        port: int = 22,
        timeout: int = 60,
        *,
        read_only: bool = False,
    ) -> LabCommandTransport:
        if decision.selected_transport == TransportKind.netmiko:
            return NetmikoCommandTransport(decision, credentials, host, port, timeout)
        if decision.selected_transport == TransportKind.paramiko:
            return ParamikoCommandTransport(credentials, host, port, timeout)
        if read_only and decision.selected_transport == TransportKind.custom_cli and decision.fallback_transport == TransportKind.paramiko:
            return ParamikoCommandTransport(credentials, host, port, timeout)
        raise SafetyError(f"No runnable lab transport is available for {decision.selected_transport.value}")


class RealLabApplyRunner:
    def __init__(self, transport_factory: LabTransportBuilder | None = None):
        self.transport_factory = transport_factory
        self.default_factory = LabSshTransportFactory()

    def execute(
        self,
        evaluation: RuntimeApplyEvaluation,
        credentials: RuntimeCredentials,
        *,
        port: int = 22,
        timeout: int = 60,
    ) -> RealLabApplyResult:
        decision = evaluation.decision
        if not decision.allowed:
            raise SafetyError("Real lab apply runner cannot execute until Apply Safety Kernel allows the request")
        if evaluation.device is None or evaluation.transport_decision is None:
            raise SafetyError("Real lab apply runner requires a device and runtime decision")
        if not evaluation.internal_commands:
            raise SafetyError("Real lab apply runner requires a non-empty validated command plan")
        host = str(evaluation.device.management_ip or evaluation.device.ip_address)
        transport = self._create_transport(evaluation.transport_decision, credentials, host, port, timeout)
        contract = get_vendor_driver_contract(evaluation.transport_decision.family)
        explicit_secrets = [credentials.password or "", credentials.enable_password or ""]
        executed: list[LabApplyCommand] = []
        outputs: list[LabCommandResult] = []
        failed = False
        error: str | None = None
        try:
            transport.open()
            for rendered in evaluation.internal_commands:
                result = transport.run_command(rendered.command, timeout_seconds=timeout)
                output = mask_secrets(result.output, explicit_secrets=[secret for secret in explicit_secrets if secret])
                command_failed = (not result.success) or _matches_any(contract.error_patterns, result.output)
                command_error = result.error or ("Vendor error pattern detected" if command_failed and result.success else None)
                outputs.append(
                    LabCommandResult(
                        command=_safe_command(rendered),
                        output=output,
                        success=not command_failed,
                        error=command_error,
                        secret=rendered.secret,
                    )
                )
                executed.append(LabApplyCommand(command=_safe_command(rendered), secret=rendered.secret))
                if command_failed:
                    failed = True
                    error = command_error or "Command failed"
                    break
        finally:
            transport.close()
        return RealLabApplyResult(
            executed=not failed,
            transport_kind=evaluation.transport_decision.selected_transport.value,
            command_count=len(executed),
            commands=executed,
            outputs=outputs,
            failed=failed,
            error=error,
        )

    def _create_transport(
        self,
        decision: TransportDecision,
        credentials: RuntimeCredentials,
        host: str,
        port: int,
        timeout: int,
    ) -> LabCommandTransport:
        if self.transport_factory is not None:
            return self.transport_factory(decision, credentials, host, port, timeout)
        return self.default_factory.create(decision, credentials, host, port, timeout)


def _safe_command(command: RenderedCommand) -> str:
    return command.redacted() if command.secret else mask_secrets(command.command)


def _matches_any(patterns: tuple[str, ...], output: str) -> bool:
    return any(re.search(pattern, output, re.IGNORECASE) for pattern in patterns)


def _netmiko_device_type(decision: TransportDecision) -> str:
    mapping = {
        "CiscoIOSDriver": "cisco_ios",
        "CiscoNXOSDriver": "cisco_nxos",
        "CiscoASADriver": "cisco_asa",
        "HuaweiVRPDriver": "huawei_vrp",
        "HPComwareDriver": "hp_comware",
        "HPEProCurveDriver": "hp_procurve",
        "DellPowerConnectDriver": "dell_powerconnect",
    }
    return mapping.get(decision.driver_name, decision.family.value)
