from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import CommandPhase, CommandPlan, CommandStep, Device, PromptResponse


def plan_to_dict(plan: CommandPlan, redact_secrets: bool = False) -> dict[str, Any]:
    return {
        "device": {
            "label": plan.device.label,
            "ip_address": plan.device.ip_address,
            "vendor": plan.device.vendor,
            "model": plan.device.model,
            "category": plan.device.category,
            "location": plan.device.location,
            "contact": plan.device.contact,
            "status": plan.device.status,
            "metadata": plan.device.metadata,
        },
        "driver": plan.driver,
        "operation": plan.operation,
        "commands": _redacted_legacy_commands(plan, redact_secrets=redact_secrets),
        "save_commands": list(plan.save_commands),
        "verify_commands": list(plan.verify_commands),
        "warnings": list(plan.warnings),
        "read_only": plan.read_only,
        "transport": plan.transport,
        "netmiko_device_type": plan.netmiko_device_type,
        "steps": [_step_to_dict(step, redact_secrets=redact_secrets) for step in plan.execution_steps],
    }


def plans_to_dict(plans: list[CommandPlan], redact_secrets: bool = False) -> dict[str, Any]:
    return {"version": 1, "plans": [plan_to_dict(plan, redact_secrets=redact_secrets) for plan in plans]}


def write_plans(path: str | Path, plans: list[CommandPlan], redact_secrets: bool = False) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(plans_to_dict(plans, redact_secrets=redact_secrets), ensure_ascii=False, indent=2), encoding="utf-8")


def read_plans(path: str | Path) -> list[CommandPlan]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        version = payload.get("version", 1)
        if version != 1:
            raise ValueError(f"Unsupported plan file version: {version}")
        raw_plans = payload.get("plans")
    else:
        raw_plans = payload
    if not isinstance(raw_plans, list):
        raise ValueError("Plan file must contain a list of plans")
    return [_plan_from_dict(item) for item in raw_plans]


def _step_to_dict(step: CommandStep, redact_secrets: bool = False) -> dict[str, Any]:
    return {
        "command": "<redacted>" if redact_secrets and step.secret else step.command,
        "phase": step.phase.value,
        "responses": [
            {
                "pattern": response.pattern,
                "response": "<redacted>" if redact_secrets and response.hidden else response.response,
                "hidden": response.hidden,
            }
            for response in step.responses
        ],
        "expected_prompt": step.expected_prompt,
        "read_only": step.read_only,
        "secret": step.secret,
        "error_patterns": list(step.error_patterns),
    }


def _redacted_legacy_commands(plan: CommandPlan, redact_secrets: bool = False) -> list[str]:
    if not redact_secrets:
        return list(plan.commands)
    secret_commands = {step.command for step in plan.execution_steps if step.secret}
    return ["<redacted>" if command in secret_commands else command for command in plan.commands]


def _plan_from_dict(raw: dict[str, Any]) -> CommandPlan:
    if not isinstance(raw, dict):
        raise ValueError("Plan item must be an object")
    device = Device(**raw["device"])
    steps = tuple(_step_from_dict(item) for item in raw.get("steps", ()))
    return CommandPlan(
        device=device,
        driver=raw["driver"],
        operation=raw["operation"],
        commands=tuple(raw.get("commands", ())),
        save_commands=tuple(raw.get("save_commands", ())),
        verify_commands=tuple(raw.get("verify_commands", ())),
        warnings=tuple(raw.get("warnings", ())),
        read_only=bool(raw.get("read_only", False)),
        transport=raw.get("transport", "paramiko"),
        netmiko_device_type=raw.get("netmiko_device_type"),
        steps=steps,
    )


def _step_from_dict(raw: dict[str, Any]) -> CommandStep:
    return CommandStep(
        command=raw["command"],
        phase=CommandPhase(raw.get("phase", CommandPhase.exec.value)),
        responses=tuple(
            PromptResponse(
                pattern=response["pattern"],
                response=response["response"],
                hidden=bool(response.get("hidden", False)),
            )
            for response in raw.get("responses", ())
        ),
        expected_prompt=raw.get("expected_prompt"),
        read_only=bool(raw.get("read_only", False)),
        secret=bool(raw.get("secret", False)),
        error_patterns=tuple(raw.get("error_patterns", ())),
    )
