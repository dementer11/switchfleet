from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CommandResult:
    command: str
    output: str
    failed: bool = False


class CliTransport(Protocol):
    def connect(self) -> None:
        ...

    def run(self, command: str) -> CommandResult:
        ...

    def close(self) -> None:
        ...
