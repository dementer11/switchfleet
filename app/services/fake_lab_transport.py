from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.lab_apply import LabApplyCommand
from app.services.vendor_command_templates import RenderedCommand
from app.utils.masking import mask_secrets


@dataclass
class FakeLabTransport:
    transport_kind: str
    connected: bool = False
    executed_commands: list[LabApplyCommand] = field(default_factory=list)

    def connect(self) -> None:
        self.connected = True

    def execute(self, commands: list[RenderedCommand]) -> list[LabApplyCommand]:
        if not self.connected:
            self.connect()
        self.executed_commands = [
            LabApplyCommand(command=command.redacted() if command.secret else mask_secrets(command.command), secret=command.secret)
            for command in commands
        ]
        return self.executed_commands

    def close(self) -> None:
        self.connected = False

