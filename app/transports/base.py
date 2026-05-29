from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CommandExecutionResult:
    command: str
    output: str
    success: bool
    error: str | None = None


class Transport(Protocol):
    def open(self) -> None:
        ...

    def close(self) -> None:
        ...

    def send_command(self, command: str, timeout_seconds: int = 60) -> CommandExecutionResult:
        ...

    def send_config(self, commands: list[str], timeout_seconds: int = 60) -> list[CommandExecutionResult]:
        ...

