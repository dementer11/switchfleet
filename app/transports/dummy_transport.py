from __future__ import annotations

from app.transports.base import CommandExecutionResult


class DummyTransport:
    def __init__(self) -> None:
        self.opened = False
        self.commands: list[str] = []

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def send_command(self, command: str, timeout_seconds: int = 60) -> CommandExecutionResult:
        self.commands.append(command)
        return CommandExecutionResult(command=command, output=f"{command}\nok", success=True)

    def send_config(self, commands: list[str], timeout_seconds: int = 60) -> list[CommandExecutionResult]:
        return [self.send_command(command, timeout_seconds=timeout_seconds) for command in commands]

