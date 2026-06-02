from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from app.core.exceptions import ConfigApplyNotAllowedError, SafetyError
from app.core.transport_strategy import DeviceFamily
from app.core.vendor_driver_contracts import VendorOperation, get_vendor_driver_contract
from app.utils.masking import mask_secrets


SECRET_PLACEHOLDERS = {"password", "secret", "new_password", "enable_password"}


@dataclass(frozen=True)
class RenderedCommand:
    command: str
    secret: bool = False

    def redacted(self) -> str:
        return mask_secrets(self.command)

    def to_safe_dict(self) -> dict[str, Any]:
        return {"command": self.redacted() if self.secret else mask_secrets(self.command), "secret": self.secret}


def command_hash(commands: list[RenderedCommand] | list[dict[str, Any]] | list[str]) -> str:
    lines: list[str] = []
    for command in commands:
        if isinstance(command, RenderedCommand):
            lines.append(command.redacted() if command.secret else mask_secrets(command.command))
        elif isinstance(command, dict):
            text = str(command.get("command") or "")
            lines.append(mask_secrets(text))
        else:
            lines.append(mask_secrets(str(command)))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


class VendorCommandTemplateService:
    def render(
        self,
        family: DeviceFamily,
        operation: VendorOperation | str,
        parameters: dict[str, Any],
    ) -> list[RenderedCommand]:
        op = operation if isinstance(operation, VendorOperation) else VendorOperation(str(operation))
        contract = get_vendor_driver_contract(family)
        if not contract.supports_operation(op):
            raise ConfigApplyNotAllowedError(f"{family.value} does not support operation {op.value}")
        if op == VendorOperation.read_backup:
            return [RenderedCommand(command) for command in contract.read_only_commands]
        templates = contract.config_command_templates.get(op)
        if not templates:
            raise ConfigApplyNotAllowedError(f"{family.value} has no certified template for operation {op.value}")
        self._validate_parameters(op, parameters)
        rendered = [
            RenderedCommand(
                command=template.format(**parameters),
                secret=any("{" + placeholder + "}" in template for placeholder in SECRET_PLACEHOLDERS),
            )
            for template in templates
        ]
        blocked = [command.command for command in rendered if contract.blocks_command(command.command)]
        if blocked:
            raise SafetyError(f"Template for {family.value}/{op.value} rendered forbidden command(s)")
        return rendered

    def validate_command_plan(
        self,
        family: DeviceFamily,
        operation: VendorOperation | str,
        parameters: dict[str, Any],
        command_plan: list[dict[str, Any]] | list[RenderedCommand],
    ) -> list[str]:
        expected = self.render(family, operation, parameters)
        actual_commands = [item.command if isinstance(item, RenderedCommand) else str(item.get("command") or "") for item in command_plan]
        expected_commands = [item.command for item in expected]
        errors: list[str] = []
        if len(actual_commands) != len(expected_commands):
            errors.append("Command plan length does not match vendor template")
            return errors
        for index, (actual, template) in enumerate(zip(actual_commands, expected_commands, strict=True), start=1):
            if not self._matches_rendered_command(actual, template, parameters):
                errors.append(f"Command {index} does not match the vendor template for {family.value}")
        return errors

    def safe_command_plan(self, commands: list[RenderedCommand]) -> list[dict[str, Any]]:
        return [command.to_safe_dict() for command in commands]

    def _validate_parameters(self, operation: VendorOperation, parameters: dict[str, Any]) -> None:
        required_by_operation: dict[VendorOperation, set[str]] = {
            VendorOperation.password_change: {"username", "password", "level"},
            VendorOperation.vlan_create: {"vlan_id", "name"},
            VendorOperation.vlan_assign_port: {"interface", "vlan_id"},
        }
        missing = sorted(required_by_operation.get(operation, set()) - set(parameters))
        if missing:
            raise SafetyError(f"Missing required command template parameter(s): {', '.join(missing)}")
        if "vlan_id" in parameters:
            vlan_id = int(parameters["vlan_id"])
            if vlan_id < 1 or vlan_id > 4094:
                raise SafetyError("VLAN ID must be in range 1..4094")
        if "level" in parameters:
            try:
                level = int(parameters["level"])
            except (TypeError, ValueError) as exc:
                raise SafetyError("Privilege level must be an integer") from exc
            if level < 0 or level > 15:
                raise SafetyError("Privilege level must be in range 0..15")
        for key, raw_value in parameters.items():
            if isinstance(raw_value, str) and re.search(r"[\r\n;&|`$]", raw_value):
                raise SafetyError(f"Unsafe shell/control character in parameter {key}")

    def _matches_rendered_command(self, actual: str, expected: str, parameters: dict[str, Any]) -> bool:
        if actual == expected:
            return True
        redacted_expected = expected
        for key in SECRET_PLACEHOLDERS:
            value = parameters.get(key)
            if value:
                redacted_expected = redacted_expected.replace(str(value), "<redacted>")
        return mask_secrets(actual) == mask_secrets(redacted_expected)
