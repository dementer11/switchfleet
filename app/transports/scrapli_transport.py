from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.transports.base import CommandExecutionResult


@dataclass(frozen=True)
class ScrapliConnectionParams:
    host: str
    platform: str
    username: str
    password: str
    port: int = 22
    timeout_socket: int = 15
    timeout_transport: int = 60


class ScrapliTransport:
    def __init__(self, params: ScrapliConnectionParams):
        self.params = params
        self._connection: Any = None

    def open(self) -> None:
        from scrapli import Scrapli

        self._connection = Scrapli(
            host=self.params.host,
            auth_username=self.params.username,
            auth_password=self.params.password,
            auth_strict_key=False,
            platform=self.params.platform,
            port=self.params.port,
            timeout_socket=self.params.timeout_socket,
            timeout_transport=self.params.timeout_transport,
        )
        self._connection.open()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
        self._connection = None

    def send_command(self, command: str, timeout_seconds: int = 60) -> CommandExecutionResult:
        if self._connection is None:
            raise RuntimeError("Scrapli transport is not open")
        response = self._connection.send_command(command, timeout_ops=timeout_seconds)
        return CommandExecutionResult(command=command, output=response.result, success=not response.failed)

    def send_config(self, commands: list[str], timeout_seconds: int = 60) -> list[CommandExecutionResult]:
        if self._connection is None:
            raise RuntimeError("Scrapli transport is not open")
        response = self._connection.send_configs(commands, timeout_ops=timeout_seconds)
        return [
            CommandExecutionResult(command=item.channel_input, output=item.result, success=not item.failed)
            for item in response
        ]

