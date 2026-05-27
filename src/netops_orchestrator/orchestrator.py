from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from .audit import JsonlAuditLog
from .drivers.registry import driver_for
from .models import AccessLevel, AclRule, CommandPlan, Device, PortChange, VlanChange
from .transports.base import CliTransport, CommandResult


def password_plans(
    devices: Iterable[Device],
    username: str,
    new_password: str,
    level: AccessLevel = AccessLevel.admin,
) -> list[CommandPlan]:
    return [
        driver_for(device).change_password(username=username, new_password=new_password, level=level)
        for device in devices
    ]


def acl_plans(devices: Iterable[Device], acl_name: str, rules: list[AclRule]) -> list[CommandPlan]:
    return [driver_for(device).configure_acl(acl_name=acl_name, rules=rules) for device in devices]


def vlan_plans(devices: Iterable[Device], change: VlanChange) -> list[CommandPlan]:
    return [driver_for(device).configure_vlan(change) for device in devices]


def port_plans(devices: Iterable[Device], change: PortChange) -> list[CommandPlan]:
    return [driver_for(device).configure_port(change) for device in devices]


def backup_plans(devices: Iterable[Device]) -> list[CommandPlan]:
    return [driver_for(device).backup_config() for device in devices]


def apply_plan(
    plan: CommandPlan,
    transport: CliTransport,
    audit: JsonlAuditLog | None = None,
    stop_on_error: bool = True,
) -> list[CommandResult]:
    if audit:
        audit.write(
            "plan_start",
            {
                "device": plan.device.ip_address,
                "label": plan.device.label,
                "driver": plan.driver,
                "operation": plan.operation,
                "commands_count": len(plan.all_commands),
            },
        )

    results: list[CommandResult] = []
    if not plan.all_commands:
        if audit:
            audit.write(
                "plan_skipped",
                {
                    "device": plan.device.ip_address,
                    "label": plan.device.label,
                    "driver": plan.driver,
                    "operation": plan.operation,
                    "reason": "empty command plan",
                },
            )
        return results

    transport.connect()
    try:
        for command in plan.all_commands:
            result = transport.run(command)
            results.append(result)
            if audit:
                audit.write(
                    "command_result",
                    {
                        "device": plan.device.ip_address,
                        "command": command,
                        "failed": result.failed,
                    },
                )
            if result.failed and stop_on_error:
                break
    finally:
        transport.close()

    if audit:
        audit.write(
            "plan_finish",
            {
                "device": plan.device.ip_address,
                "failed": any(result.failed for result in results),
                "results_count": len(results),
            },
        )
    return results


def backup_config(plan: CommandPlan, transport: CliTransport, output_dir: str | Path) -> Path | None:
    if plan.operation != "backup":
        raise ValueError(f"Expected backup plan, got {plan.operation}")
    if not plan.all_commands:
        return None

    results = apply_plan(plan, transport, stop_on_error=False)
    output = _format_backup_output(plan, results)
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / _backup_filename(plan)
    path.write_text(output, encoding="utf-8")
    return path


def _format_backup_output(plan: CommandPlan, results: list[CommandResult]) -> str:
    lines = [
        f"# device: {plan.device.label}",
        f"# ip: {plan.device.ip_address}",
        f"# vendor: {plan.device.vendor}",
        f"# model: {plan.device.model}",
        f"# driver: {plan.driver}",
        f"# captured_at: {datetime.now(timezone.utc).isoformat()}",
        "",
    ]
    for result in results:
        lines.append(f"### command: {result.command}")
        lines.append(result.output.rstrip())
        lines.append("")
    return "\n".join(lines)


def _backup_filename(plan: CommandPlan) -> str:
    label = _safe_filename(plan.device.label or plan.device.ip_address)
    ip = _safe_filename(plan.device.ip_address)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ip}_{label}_{plan.driver}_{ts}.cfg"


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_.") or "device"
