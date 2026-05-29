from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models import CommandStep


@dataclass(frozen=True)
class CommandResult:
    command: str
    output: str
    failed: bool = False
    phase: str = "exec"
    redacted_command: str | None = None
    error: str | None = None


class CliTransport(Protocol):
    def connect(self) -> None:
        ...

    def run(self, command: str) -> CommandResult:
        ...

    def run_steps(self, steps: tuple[CommandStep, ...], stop_on_error: bool = True) -> list[CommandResult]:
        ...

    def close(self) -> None:
        ...
