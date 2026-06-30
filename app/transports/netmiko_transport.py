from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.transports.base import CommandExecutionResult


@dataclass(frozen=True)
class NetmikoConnectionParams:
    host: str
    device_type: str
    username: str
    password: str
    port: int = 22
    timeout: int = 15
    conn_timeout: int | None = None
    auth_timeout: int | None = None
    banner_timeout: int | None = None
    enable_password: str | None = None


class NetmikoTransport:
    def __init__(self, params: NetmikoConnectionParams):
        self.params = params
        self._connection: Any = None

    def open(self) -> None:
        from netmiko import ConnectHandler

        kwargs: dict[str, Any] = {
            "host": self.params.host,
            "device_type": self.params.device_type,
            "username": self.params.username,
            "password": self.params.password,
            "port": self.params.port,
            "timeout": self.params.timeout,
            "conn_timeout": self.params.conn_timeout or self.params.timeout,
            "auth_timeout": self.params.auth_timeout or self.params.timeout,
            "banner_timeout": self.params.banner_timeout or self.params.timeout,
            "fast_cli": False,
        }
        if self.params.enable_password:
            kwargs["secret"] = self.params.enable_password
        self._connection = ConnectHandler(**kwargs)
        if self.params.enable_password:
            self._connection.enable()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.disconnect()
        self._connection = None

    def send_command(self, command: str, timeout_seconds: int = 60) -> CommandExecutionResult:
        if self._connection is None:
            raise RuntimeError("Netmiko transport is not open")
        output = self._connection.send_command_timing(command, read_timeout=timeout_seconds)
        return CommandExecutionResult(command=command, output=output, success=True)

    def send_config(self, commands: list[str], timeout_seconds: int = 60) -> list[CommandExecutionResult]:
        if self._connection is None:
            raise RuntimeError("Netmiko transport is not open")
        output = self._connection.send_config_set(commands, read_timeout=timeout_seconds, cmd_verify=False)
        return [CommandExecutionResult(command="\n".join(commands), output=output, success=True)]
