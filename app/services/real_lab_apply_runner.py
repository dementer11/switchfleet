from __future__ import annotations

import re
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, cast

from app.core.exceptions import SafetyError
from app.core.transport_strategy import DeviceFamily, TransportDecision, TransportKind
from app.core.vendor_driver_contracts import get_vendor_driver_contract
from app.schemas.lab_apply import ApplySafetyDecisionRead
from app.schemas.lab_apply import LabApplyCommand
from app.services.transport_runtime import RuntimeCredentials
from app.services.vendor_command_templates import RenderedCommand
from app.transports.base import CommandExecutionResult
from app.transports.netmiko_transport import NetmikoConnectionParams, NetmikoTransport
from app.utils.masking import mask_secrets


PAGING_MARKER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-{2,}\s*More\s*-{2,}", re.IGNORECASE),
    re.compile(r"<-{2,}\s*More\s*-{2,}>", re.IGNORECASE),
    re.compile(r"\bMore:\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"Press any key to continue", re.IGNORECASE),
    re.compile(r"press ENTER to continue", re.IGNORECASE),
    re.compile(r"^\s*[<\-\s]*More[>\-\s:]*$", re.IGNORECASE | re.MULTILINE),
)
IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
COMMON_PROMPT_PATTERNS: tuple[str, ...] = (
    r"<[^>\r\n]+>\s*$",
    r"\[[^\]\r\n]+\]\s*$",
    r"[\w.\-()]+[>#]\s*$",
    r"[>#]\s*$",
)


@dataclass(frozen=True)
class LegacySshOptions:
    kex: tuple[str, ...]
    key_types: tuple[str, ...]
    ciphers: tuple[str, ...]


@dataclass(frozen=True)
class PagingMarker:
    text: str
    continuation: str


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


class InteractivePagingTransport(Protocol):
    def run_read_only_backup_command(
        self,
        command: str,
        timeout_seconds: int = 60,
        *,
        max_pages: int = 500,
        max_bytes: int = 10 * 1024 * 1024,
    ) -> CommandExecutionResult:
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
        self.decision = decision
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

    def run_read_only_backup_command(
        self,
        command: str,
        timeout_seconds: int = 60,
        *,
        max_pages: int = 500,
        max_bytes: int = 10 * 1024 * 1024,
    ) -> CommandExecutionResult:
        result = self._transport.send_command(command, timeout_seconds=timeout_seconds)
        return _continue_paged_backup_result(
            decision=self.decision,
            command=command,
            initial_result=result,
            send_continuation=lambda key: self._transport.send_command(key, timeout_seconds=timeout_seconds),
            timeout_seconds=timeout_seconds,
            max_pages=max_pages,
            max_bytes=max_bytes,
        )


class ParamikoCommandTransport:
    def __init__(
        self,
        decision: TransportDecision,
        credentials: RuntimeCredentials,
        host: str,
        port: int,
        timeout: int,
    ):
        self.decision = decision
        self.credentials = credentials
        self.host = host
        self.port = port
        self.timeout = timeout
        self._client: Any | None = None
        self._channel: Any | None = None
        self._last_output = ""

    def open(self) -> None:
        try:
            import paramiko  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(build_transport_diagnostic(self.decision, "connect", "Paramiko is required")) from exc
        try:
            client, channel = self._open_client(paramiko)
        except Exception as exc:
            self.close()
            phase = _connection_failure_phase(exc)
            raise RuntimeError(build_transport_diagnostic(self.decision, phase, str(exc))) from exc
        try:
            self._client = client
            self._channel = channel
            channel.settimeout(self.timeout)
            output, completed = self._read_until_prompt()
            if not completed:
                raise TimeoutError(f"Timed out waiting for prompt after {self.timeout}s")
            self._last_output = output
        except Exception as exc:
            self.close()
            raise RuntimeError(
                build_transport_diagnostic(self.decision, "prompt", str(exc), output=self._last_output)
            ) from exc

    def close(self) -> None:
        if self._channel is not None:
            self._channel.close()
        if self._client is not None:
            self._client.close()
        self._channel = None
        self._client = None

    def run_command(self, command: str, timeout_seconds: int = 60) -> CommandExecutionResult:
        if self._channel is None:
            raise RuntimeError("Paramiko lab transport is not open")
        self._channel.send(command + "\n")
        output, completed = self._read_until_prompt(timeout_seconds)
        self._last_output = output
        error = None
        if not completed:
            error = build_transport_diagnostic(
                self.decision,
                "command",
                f"Timed out waiting for prompt after {timeout_seconds}s",
                output=output,
            )
        return CommandExecutionResult(
            command=command,
            output=output,
            success=completed,
            error=error,
        )

    def run_read_only_backup_command(
        self,
        command: str,
        timeout_seconds: int = 60,
        *,
        max_pages: int = 500,
        max_bytes: int = 10 * 1024 * 1024,
    ) -> CommandExecutionResult:
        if self._channel is None:
            raise RuntimeError("Paramiko lab transport is not open")
        self._channel.send(command + "\n")
        return self._read_backup_until_prompt_with_pager(
            command,
            timeout_seconds=timeout_seconds,
            max_pages=max_pages,
            max_bytes=max_bytes,
        )

    def _open_client(self, paramiko: Any) -> tuple[Any, Any]:
        if legacy_ssh_options_for_decision(self.decision) is not None:
            return self._open_legacy_client(paramiko)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                self.host,
                port=self.port,
                username=self.credentials.username,
                password=self.credentials.password,
                look_for_keys=False,
                allow_agent=False,
                timeout=self.timeout,
                banner_timeout=self.timeout,
                auth_timeout=self.timeout,
            )
            channel = client.invoke_shell(width=200, height=80)
            return client, channel
        except Exception:
            client.close()
            raise

    def _open_legacy_client(self, paramiko: Any) -> tuple[Any, Any]:
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        transport = paramiko.Transport(sock)
        try:
            _apply_legacy_ssh_options(transport.get_security_options(), legacy_ssh_options_for_decision(self.decision))
            transport.start_client(timeout=self.timeout)
            transport.auth_password(self.credentials.username, self.credentials.password or "")
            client = paramiko.SSHClient()
            client._transport = transport
            channel = transport.open_session(timeout=self.timeout)
            channel.get_pty(width=200, height=80)
            channel.invoke_shell()
            return client, channel
        except Exception:
            transport.close()
            raise

    def _read_until_prompt(self, timeout_seconds: int | None = None) -> tuple[str, bool]:
        if self._channel is None:
            raise RuntimeError("Paramiko lab transport is not open")
        deadline = time.monotonic() + float(timeout_seconds or self.timeout)
        chunks: list[str] = []
        prompt = prompt_regex_for_decision(self.decision)
        while time.monotonic() < deadline:
            try:
                if self._channel.recv_ready():
                    data = self._channel.recv(65535).decode("utf-8", errors="replace")
                    chunks.append(data)
                    output = "".join(chunks)
                    self._last_output = output
                    if prompt.search(output):
                        return output, True
                else:
                    time.sleep(0.05)
            except socket.timeout:
                break
        output = "".join(chunks)
        self._last_output = output
        return output, False

    def _read_backup_until_prompt_with_pager(
        self,
        command: str,
        *,
        timeout_seconds: int,
        max_pages: int,
        max_bytes: int,
    ) -> CommandExecutionResult:
        if self._channel is None:
            raise RuntimeError("Paramiko lab transport is not open")
        deadline = time.monotonic() + float(timeout_seconds)
        output = ""
        pages = 0
        prompt = prompt_regex_for_decision(self.decision)
        while time.monotonic() < deadline:
            try:
                if self._channel.recv_ready():
                    data = self._channel.recv(65535).decode("utf-8", errors="replace")
                    output += data
                    self._last_output = output
                    if len(output.encode("utf-8", errors="replace")) > max_bytes:
                        return _paging_failure_result(
                            self.decision,
                            command,
                            output,
                            f"Exceeded max_bytes={max_bytes} while continuing paged backup output",
                        )
                    marker = find_paging_marker(output)
                    if marker is not None:
                        pages += 1
                        if pages > max_pages:
                            return _paging_failure_result(
                                self.decision,
                                command,
                                output,
                                f"Exceeded max_pages={max_pages} while continuing paged backup output",
                            )
                        output = strip_paging_markers(output)
                        self._last_output = output
                        self._channel.send(marker.continuation)
                        continue
                    if prompt.search(output):
                        return CommandExecutionResult(command=command, output=strip_paging_markers(output), success=True)
                else:
                    time.sleep(0.05)
            except socket.timeout:
                break
        return _paging_failure_result(
            self.decision,
            command,
            output,
            f"Timed out waiting for prompt after {timeout_seconds}s while continuing paged backup output",
        )


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
            return ParamikoCommandTransport(decision, credentials, host, port, timeout)
        if read_only and decision.selected_transport == TransportKind.custom_cli and decision.fallback_transport == TransportKind.paramiko:
            return ParamikoCommandTransport(decision, credentials, host, port, timeout)
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


def prompt_regex_for_decision(decision: TransportDecision) -> re.Pattern[str]:
    contract = get_vendor_driver_contract(decision.family)
    patterns = _dedupe_patterns(contract.prompt_patterns + COMMON_PROMPT_PATTERNS)
    return re.compile("|".join(f"(?:{pattern})" for pattern in patterns))


def output_has_paging_marker(output: str) -> bool:
    return any(pattern.search(output) for pattern in PAGING_MARKER_PATTERNS)


def find_paging_marker(output: str) -> PagingMarker | None:
    matches = [match for pattern in PAGING_MARKER_PATTERNS if (match := pattern.search(output)) is not None]
    if not matches:
        return None
    match = min(matches, key=lambda item: item.start())
    text = match.group(0)
    return PagingMarker(text=text, continuation="\n" if "enter" in text.casefold() else " ")


def strip_paging_markers(output: str) -> str:
    cleaned = output
    for pattern in PAGING_MARKER_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return cleaned


def run_read_only_backup_command(
    transport: LabCommandTransport,
    command: str,
    timeout_seconds: int = 60,
) -> CommandExecutionResult:
    interactive = getattr(transport, "run_read_only_backup_command", None)
    if callable(interactive):
        interactive_backup = cast(Callable[..., CommandExecutionResult], interactive)
        return interactive_backup(command, timeout_seconds=timeout_seconds)
    return transport.run_command(command, timeout_seconds=timeout_seconds)


def _continue_paged_backup_result(
    *,
    decision: TransportDecision,
    command: str,
    initial_result: CommandExecutionResult,
    send_continuation: Callable[[str], CommandExecutionResult],
    timeout_seconds: int,
    max_pages: int,
    max_bytes: int,
) -> CommandExecutionResult:
    if not initial_result.success:
        return initial_result
    deadline = time.monotonic() + float(timeout_seconds)
    output = initial_result.output
    pages = 0
    saw_paging = False
    while (marker := find_paging_marker(output)) is not None:
        saw_paging = True
        pages += 1
        if pages > max_pages:
            return _paging_failure_result(
                decision,
                command,
                output,
                f"Exceeded max_pages={max_pages} while continuing paged backup output",
            )
        if len(output.encode("utf-8", errors="replace")) > max_bytes:
            return _paging_failure_result(
                decision,
                command,
                output,
                f"Exceeded max_bytes={max_bytes} while continuing paged backup output",
            )
        if time.monotonic() > deadline:
            return _paging_failure_result(
                decision,
                command,
                output,
                f"Timed out waiting for prompt after {timeout_seconds}s while continuing paged backup output",
            )
        output = strip_paging_markers(output)
        continuation = send_continuation(marker.continuation)
        output += continuation.output
        if not continuation.success:
            return _paging_failure_result(
                decision,
                command,
                output,
                continuation.error or "Paged backup continuation command failed",
            )
    if len(output.encode("utf-8", errors="replace")) > max_bytes:
        return _paging_failure_result(
            decision,
            command,
            output,
            f"Exceeded max_bytes={max_bytes} while continuing paged backup output",
        )
    if saw_paging and not prompt_regex_for_decision(decision).search(output):
        return _paging_failure_result(
            decision,
            command,
            output,
            "Paged backup continuation ended before final prompt was detected",
        )
    return CommandExecutionResult(command=command, output=strip_paging_markers(output), success=True)


def legacy_ssh_options_for_decision(decision: TransportDecision) -> LegacySshOptions | None:
    legacy_families = {DeviceFamily.eltex, DeviceFamily.qtech, DeviceFamily.hpe_comware}
    if decision.family not in legacy_families:
        return None
    return LegacySshOptions(
        kex=("diffie-hellman-group1-sha1", "diffie-hellman-group14-sha1"),
        key_types=("ssh-rsa",),
        ciphers=("3des-cbc", "aes128-cbc"),
    )


def build_transport_diagnostic(
    decision: TransportDecision,
    phase: str,
    reason: str,
    *,
    output: str | None = None,
) -> str:
    parts = [
        "Lab SSH transport failed",
        f"driver={decision.driver_name}",
        f"transport={decision.selected_transport.value}",
        f"family={decision.family.value}",
        f"platform={decision.platform or 'unknown'}",
        f"phase={phase}",
        f"reason={_sanitize_diagnostic_text(reason)}",
    ]
    snippet = _safe_output_snippet(output or "")
    if snippet:
        parts.append(f"last_output={snippet}")
    return "; ".join(parts)


def paging_diagnostic(
    decision: TransportDecision,
    command: str,
    reason: str = "paging marker detected",
    *,
    output: str | None = None,
) -> str:
    parts = [
        "Incomplete backup output",
        f"driver={decision.driver_name}",
        f"transport={decision.selected_transport.value}",
        f"family={decision.family.value}",
        f"platform={decision.platform or 'unknown'}",
        "phase=paging",
        f"command={mask_secrets(command)}",
        f"reason={_sanitize_diagnostic_text(reason)}",
    ]
    snippet = _safe_output_snippet(output or "")
    if snippet:
        parts.append(f"last_output={snippet}")
    return "; ".join(parts)


def _paging_failure_result(decision: TransportDecision, command: str, output: str, reason: str) -> CommandExecutionResult:
    return CommandExecutionResult(
        command=command,
        output=output,
        success=False,
        error=paging_diagnostic(decision, command, reason, output=output),
    )


def _connection_failure_phase(exc: Exception) -> str:
    text = f"{type(exc).__name__} {exc}".casefold()
    if "auth" in text or "permission" in text or "credential" in text:
        return "auth"
    return "connect"


def _dedupe_patterns(patterns: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for pattern in patterns:
        if pattern not in seen:
            seen.add(pattern)
            unique.append(pattern)
    return tuple(unique)


def _safe_output_snippet(output: str, limit: int = 300) -> str:
    if not output:
        return ""
    sanitized = _sanitize_diagnostic_text(output).replace("\r", "\n")
    lines = [line.strip() for line in sanitized.splitlines() if line.strip()]
    snippet = "\n".join(lines[-6:])[-limit:]
    return snippet.replace("\n", " | ")


def _sanitize_diagnostic_text(text: str) -> str:
    return IPV4_PATTERN.sub("<redacted-ip>", mask_secrets(text))


def _apply_legacy_ssh_options(security_options: Any, options: LegacySshOptions | None) -> None:
    if options is None:
        return
    for attribute, preferred in (
        ("kex", options.kex),
        ("key_types", options.key_types),
        ("ciphers", options.ciphers),
    ):
        current = tuple(getattr(security_options, attribute, ()) or ())
        if not current:
            continue
        merged = tuple(item for item in preferred if item in current) + tuple(item for item in current if item not in preferred)
        if merged:
            setattr(security_options, attribute, merged)


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
