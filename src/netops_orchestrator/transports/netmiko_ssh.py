from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..models import CommandPhase, CommandStep
from .base import CommandResult
from .errors import output_has_cli_error
from .ssh_paramiko import SshCredentials


@dataclass(frozen=True)
class NetmikoConnectionOptions:
    port: int = 22
    timeout: float = 15.0
    read_timeout: float = 60.0


class NetmikoCliTransport:
    """Netmiko-backed SSH transport; command syntax remains in first-party drivers."""

    def __init__(
        self,
        host: str,
        credentials: SshCredentials,
        device_type: str,
        options: NetmikoConnectionOptions | None = None,
    ):
        self.host = host
        self.credentials = credentials
        self.device_type = device_type
        self.options = options or NetmikoConnectionOptions()
        self._connection: Any = None

    def connect(self) -> None:
        try:
            from netmiko import ConnectHandler
        except ImportError as exc:
            raise RuntimeError(
                "Netmiko is required for this transport. Install netops-orchestrator with netmiko."
            ) from exc

        params = {
            "device_type": self.device_type,
            "host": self.host,
            "port": self.options.port,
            "username": self.credentials.username,
            "password": self.credentials.password,
            "timeout": self.options.timeout,
            "conn_timeout": self.options.timeout,
            "auth_timeout": self.options.timeout,
            "banner_timeout": self.options.timeout,
            "fast_cli": False,
        }
        if self.credentials.enable_password:
            params["secret"] = self.credentials.enable_password

        self._connection = ConnectHandler(**params)
        if self.credentials.enable_password:
            self._connection.enable()

    def run(self, command: str) -> CommandResult:
        return self._run_exec_step(CommandStep(command))

    def run_steps(self, steps: tuple[CommandStep, ...], stop_on_error: bool = True) -> list[CommandResult]:
        if self._connection is None:
            raise RuntimeError("Transport is not connected")

        results: list[CommandResult] = []
        index = 0
        while index < len(steps):
            step = steps[index]
            if step.phase == CommandPhase.config:
                block: list[CommandStep] = []
                while index < len(steps) and steps[index].phase == CommandPhase.config:
                    block.append(steps[index])
                    index += 1
                result = self._run_config_block(tuple(block))
            else:
                result = self._run_exec_step(step)
                index += 1
            results.append(result)
            if result.failed and stop_on_error:
                break
        return results

    def _run_exec_step(self, step: CommandStep) -> CommandResult:
        if self._connection is None:
            raise RuntimeError("Transport is not connected")
        output = self._connection.send_command_timing(
            step.command,
            strip_prompt=False,
            strip_command=False,
            read_timeout=self.options.read_timeout,
        )
        for response in step.responses:
            if re.search(response.pattern, output, re.IGNORECASE):
                output += self._connection.send_command_timing(
                    response.response,
                    strip_prompt=False,
                    strip_command=False,
                    read_timeout=self.options.read_timeout,
                )
        return CommandResult(
            command=step.command,
            output=output,
            failed=output_has_cli_error(output, step.error_patterns),
            phase=step.phase.value,
            redacted_command="<redacted>" if step.secret else step.command,
        )

    def _run_config_block(self, steps: tuple[CommandStep, ...]) -> CommandResult:
        if self._connection is None:
            raise RuntimeError("Transport is not connected")
        commands = [step.command for step in steps]
        output = self._connection.send_config_set(
            commands,
            strip_prompt=False,
            strip_command=False,
            read_timeout=self.options.read_timeout,
            cmd_verify=False,
        )
        failed = output_has_cli_error(output, tuple(pattern for step in steps for pattern in step.error_patterns))
        redacted = "\n".join("<redacted>" if step.secret else step.command for step in steps)
        return CommandResult(
            command="\n".join(commands),
            output=output,
            failed=failed,
            phase=CommandPhase.config.value,
            redacted_command=redacted,
        )

    def close(self) -> None:
        if self._connection is not None:
            self._connection.disconnect()
        self._connection = None
