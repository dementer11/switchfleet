from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from collections import Counter
from pathlib import Path

from .audit import JsonlAuditLog
from .drivers.registry import driver_for
from .inventory import load_inventory
from .models import AccessLevel, AclRule, CommandPlan, PortChange, VlanChange
from .orchestrator import acl_plans, apply_plan, backup_config, backup_plans, password_plans, port_plans, vlan_plans
from .plan_io import plans_to_dict, read_plans, write_plans
from .transports.factory import TRANSPORT_CHOICES, selected_transport_label, transport_for_plan
from .transports.ssh_paramiko import SshCredentials


def main() -> None:
    parser = argparse.ArgumentParser(prog="netops", description="Network equipment orchestration.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_inventory = sub.add_parser("inventory", help="Inspect inventory and driver mapping")
    p_inventory.add_argument("path", type=Path)

    p_password = sub.add_parser("plan-password", help="Render password change command plans")
    p_password.add_argument("inventory_path", type=Path)
    p_password.add_argument("--username", required=True)
    p_password.add_argument("--new-password")
    p_password.add_argument("--new-password-stdin", action="store_true")
    p_password.add_argument("--new-password-env")
    p_password.add_argument("--level", choices=[item.value for item in AccessLevel], default=AccessLevel.admin.value)
    p_password.add_argument("--limit", type=int)
    _add_plan_output_args(p_password)

    p_acl = sub.add_parser("plan-acl", help="Render ACL command plans")
    p_acl.add_argument("inventory_path", type=Path)
    p_acl.add_argument("--acl-name", required=True)
    p_acl.add_argument(
        "--rule",
        action="append",
        required=True,
        help="Format: seq,action,protocol,source,destination[,extra]",
    )
    p_acl.add_argument("--limit", type=int)
    _add_plan_output_args(p_acl)

    p_vlan = sub.add_parser("plan-vlan", help="Render VLAN command plans")
    p_vlan.add_argument("inventory_path", type=Path)
    p_vlan.add_argument("--vlan-id", type=int, required=True)
    p_vlan.add_argument("--name")
    p_vlan.add_argument("--port", action="append", default=[])
    p_vlan.add_argument("--mode", choices=["access", "trunk"], default="access")
    p_vlan.add_argument("--limit", type=int)
    _add_plan_output_args(p_vlan)

    p_port = sub.add_parser("plan-port", help="Render port command plans")
    p_port.add_argument("inventory_path", type=Path)
    p_port.add_argument("--interface", required=True)
    p_port.add_argument("--description")
    p_port.add_argument("--enabled", choices=["true", "false"])
    p_port.add_argument("--access-vlan", type=int)
    p_port.add_argument("--trunk-vlan", action="append", type=int, default=[])
    p_port.add_argument("--limit", type=int)
    _add_plan_output_args(p_port)

    p_backup_plan = sub.add_parser("plan-backup", help="Render running/current-config backup command plans")
    p_backup_plan.add_argument("inventory_path", type=Path)
    p_backup_plan.add_argument("--limit", type=int)
    _add_plan_output_args(p_backup_plan)

    p_apply = sub.add_parser("apply", help="Apply an operation or a saved plan over SSH")
    p_apply.add_argument("inventory_path", type=Path, nargs="?")
    _add_connection_args(p_apply, require_login=False)
    p_apply.add_argument("--plan-file", type=Path)
    p_apply.add_argument("--operation", choices=["password", "acl", "vlan", "port"])
    p_apply.add_argument("--target-user")
    p_apply.add_argument("--new-password")
    p_apply.add_argument("--new-password-stdin", action="store_true")
    p_apply.add_argument("--new-password-env")
    p_apply.add_argument("--level", choices=[item.value for item in AccessLevel], default=AccessLevel.admin.value)
    p_apply.add_argument("--acl-name")
    p_apply.add_argument("--rule", action="append", default=[])
    p_apply.add_argument("--vlan-id", type=int)
    p_apply.add_argument("--name")
    p_apply.add_argument("--port", action="append", default=[])
    p_apply.add_argument("--mode", choices=["access", "trunk"], default="access")
    p_apply.add_argument("--interface")
    p_apply.add_argument("--description")
    p_apply.add_argument("--enabled", choices=["true", "false"])
    p_apply.add_argument("--access-vlan", type=int)
    p_apply.add_argument("--trunk-vlan", action="append", type=int, default=[])
    p_apply.add_argument("--limit", type=int, default=1)
    p_apply.add_argument("--canary", type=int)
    p_apply.add_argument("--dry-run", action="store_true")
    p_apply.add_argument("--pre-backup", action="store_true")
    p_apply.add_argument("--post-backup", action="store_true")
    p_apply.add_argument("--continue-on-error", action="store_true")
    p_apply.add_argument("--backup-dir", type=Path, default=Path("backups"))
    p_apply.add_argument("--audit-log", type=Path)
    p_apply.add_argument("--show-secrets", action="store_true")

    p_backup = sub.add_parser("backup", help="Capture device running/current config over SSH")
    p_backup.add_argument("inventory_path", type=Path)
    _add_connection_args(p_backup)
    p_backup.add_argument("--output-dir", type=Path, default=Path("backups"))
    p_backup.add_argument("--limit", type=int, default=1)
    p_backup.add_argument("--continue-on-error", action="store_true")

    args = parser.parse_args()
    if args.command == "inventory":
        _inventory(args.path)
    elif args.command == "plan-password":
        devices = _limit(load_inventory(args.inventory_path), args.limit)
        new_password = _secret_arg(args.new_password, args.new_password_stdin, "New password", args.new_password_env)
        plans = password_plans(
            devices,
            username=args.username,
            new_password=new_password,
            level=AccessLevel(args.level),
        )
        _emit_plans(plans, args)
    elif args.command == "plan-acl":
        devices = _limit(load_inventory(args.inventory_path), args.limit)
        plans = acl_plans(devices, acl_name=args.acl_name, rules=[_parse_acl_rule(r) for r in args.rule])
        _emit_plans(plans, args)
    elif args.command == "plan-vlan":
        devices = _limit(load_inventory(args.inventory_path), args.limit)
        change = VlanChange(vlan_id=args.vlan_id, name=args.name, ports=tuple(args.port), mode=args.mode)
        _emit_plans(vlan_plans(devices, change), args)
    elif args.command == "plan-port":
        devices = _limit(load_inventory(args.inventory_path), args.limit)
        enabled = None if args.enabled is None else args.enabled == "true"
        change = PortChange(
            interface=args.interface,
            description=args.description,
            enabled=enabled,
            access_vlan=args.access_vlan,
            trunk_vlans=tuple(args.trunk_vlan),
        )
        _emit_plans(port_plans(devices, change), args)
    elif args.command == "plan-backup":
        devices = _limit(load_inventory(args.inventory_path), args.limit)
        _emit_plans(backup_plans(devices), args)
    elif args.command == "apply":
        _apply(args)
    elif args.command == "backup":
        _backup(args)


def _inventory(path: Path) -> None:
    devices = load_inventory(path)
    by_vendor = Counter(device.vendor or "Unknown" for device in devices)
    by_driver = Counter(driver_for(device).name for device in devices)
    backup = backup_plans(devices)
    password = password_plans(devices, username="__probe__", new_password="__probe__")
    unsupported_backup = [
        {"ip": plan.device.ip_address, "vendor": plan.device.vendor, "model": plan.device.model, "driver": plan.driver}
        for plan in backup
        if not plan.commands
    ]
    print(
        json.dumps(
            {
                "devices": len(devices),
                "vendors": by_vendor,
                "drivers": by_driver,
                "capabilities": {
                    "backup_supported": sum(1 for plan in backup if plan.commands),
                    "backup_unsupported": sum(1 for plan in backup if not plan.commands),
                    "password_supported": sum(1 for plan in password if plan.commands),
                    "password_unsupported": sum(1 for plan in password if not plan.commands),
                },
                "transports": {
                    "netmiko_preferred": sum(1 for plan in backup if plan.netmiko_device_type),
                    "paramiko_preferred": sum(1 for plan in backup if not plan.netmiko_device_type),
                },
                "unsupported_backup_devices": unsupported_backup,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _apply(args: argparse.Namespace) -> None:
    plans = _read_plan_file(args.plan_file) if args.plan_file else _plans_from_apply_args(args)
    if args.canary is not None:
        if args.canary < 1:
            raise SystemExit("--canary must be >= 1")
        plans = plans[: args.canary]
    audit = JsonlAuditLog(args.audit_log) if args.audit_log else None

    if args.dry_run:
        _print_plans(plans, show_secrets=args.show_secrets)
        return

    _reject_redacted_secret_steps(plans)
    credentials = _credentials(args)
    any_failed = False
    for plan in plans:
        if not plan.all_commands:
            print(f"skipping {plan.device.ip_address}: empty {plan.operation} plan for {plan.driver}")
            any_failed = True
            if not args.continue_on_error:
                raise SystemExit(1)
            continue
        failed = False
        try:
            if args.pre_backup:
                _capture_backup_for_device(plan, credentials, args, "pre")
            print(
                f"applying {plan.operation} to {plan.device.ip_address} "
                f"with {plan.driver} via {selected_transport_label(plan, args.transport)}"
            )
            transport = _transport(plan, credentials, args)
            results = apply_plan(plan, transport, audit=audit)
            failed = any(result.failed for result in results)
            any_failed = any_failed or failed
            print("failed" if failed else "ok")
            if args.post_backup:
                _capture_backup_for_device(plan, credentials, args, "post")
        except Exception as exc:
            any_failed = True
            print(f"error {plan.device.ip_address}: {exc}", file=sys.stderr)
            if not args.continue_on_error:
                raise SystemExit(1) from exc
            continue
        if failed and not args.continue_on_error:
            raise SystemExit(1)
    if any_failed:
        raise SystemExit(1)


def _backup(args: argparse.Namespace) -> None:
    devices = _limit(load_inventory(args.inventory_path), args.limit)
    credentials = _credentials(args)
    any_failed = False
    for plan in backup_plans(devices):
        if not plan.all_commands:
            print(f"skipping {plan.device.ip_address}: no backup commands for {plan.driver}")
            any_failed = True
            if not args.continue_on_error:
                raise SystemExit(1)
            continue
        try:
            print(
                f"capturing {plan.device.ip_address} with {plan.driver} "
                f"via {selected_transport_label(plan, args.transport)}"
            )
            transport = _transport(plan, credentials, args)
            path = backup_config(plan, transport, args.output_dir, fail_on_error=True)
            print(path if path else "skipped")
        except Exception as exc:
            any_failed = True
            print(f"error {plan.device.ip_address}: {exc}", file=sys.stderr)
            if not args.continue_on_error:
                raise SystemExit(1) from exc
    if any_failed:
        raise SystemExit(1)


def _capture_backup_for_device(
    plan: CommandPlan,
    credentials: SshCredentials,
    args: argparse.Namespace,
    stage: str,
) -> None:
    backup_plan = driver_for(plan.device).backup_config()
    if not backup_plan.all_commands:
        print(f"{stage}-backup skipped for {plan.device.ip_address}: unsupported backup")
        return
    target_dir = args.backup_dir / stage
    print(f"{stage}-backup {plan.device.ip_address} via {selected_transport_label(backup_plan, args.transport)}")
    path = backup_config(backup_plan, _transport(backup_plan, credentials, args), target_dir, fail_on_error=True)
    print(path if path else "skipped")


def _read_plan_file(path: Path) -> list[CommandPlan]:
    try:
        return read_plans(path)
    except Exception as exc:
        raise SystemExit(f"Failed to read plan file {path}: {exc}") from exc


def _plans_from_apply_args(args: argparse.Namespace) -> list[CommandPlan]:
    if not args.inventory_path:
        raise SystemExit("inventory_path is required unless --plan-file is used")
    if not args.operation:
        raise SystemExit("--operation is required unless --plan-file is used")
    devices = _limit(load_inventory(args.inventory_path), args.limit)
    if args.operation == "password":
        if not args.target_user:
            raise SystemExit("--target-user is required for password operation")
        new_password = _secret_arg(args.new_password, args.new_password_stdin, "New password", args.new_password_env)
        return password_plans(
            devices,
            username=args.target_user,
            new_password=new_password,
            level=AccessLevel(args.level),
        )
    if args.operation == "acl":
        if not args.acl_name or not args.rule:
            raise SystemExit("--acl-name and at least one --rule are required for acl operation")
        return acl_plans(devices, acl_name=args.acl_name, rules=[_parse_acl_rule(r) for r in args.rule])
    if args.operation == "vlan":
        if args.vlan_id is None:
            raise SystemExit("--vlan-id is required for vlan operation")
        return vlan_plans(devices, VlanChange(args.vlan_id, name=args.name, ports=tuple(args.port), mode=args.mode))
    if args.operation == "port":
        if not args.interface:
            raise SystemExit("--interface is required for port operation")
        enabled = None if args.enabled is None else args.enabled == "true"
        return port_plans(
            devices,
            PortChange(
                interface=args.interface,
                description=args.description,
                enabled=enabled,
                access_vlan=args.access_vlan,
                trunk_vlans=tuple(args.trunk_vlan),
            ),
        )
    raise SystemExit(f"Unsupported operation: {args.operation}")


def _reject_redacted_secret_steps(plans: list[CommandPlan]) -> None:
    for plan in plans:
        for step in plan.execution_steps:
            if step.secret and step.command == "<redacted>":
                raise SystemExit(
                    "Plan contains redacted secret commands. Re-create the plan with --show-secrets, "
                    "or apply directly without --plan-file."
                )
            for response in step.responses:
                if response.hidden and response.response == "<redacted>":
                    raise SystemExit(
                        "Plan contains redacted prompt responses. Re-create the plan with --show-secrets, "
                        "or apply directly without --plan-file."
                    )


def _transport(plan: CommandPlan, credentials: SshCredentials, args: argparse.Namespace):
    return transport_for_plan(
        plan,
        credentials,
        preference=args.transport,
        port=args.ssh_port,
        timeout=args.timeout,
        read_timeout=args.read_timeout,
    )


def _credentials(args: argparse.Namespace) -> SshCredentials:
    if not args.login:
        raise SystemExit("--login is required for SSH execution")
    return SshCredentials(
        username=args.login,
        password=_secret_arg(args.password, args.password_stdin, "Login password", args.password_env),
        enable_password=_secret_arg(
            args.enable_password,
            args.enable_password_stdin,
            "Enable password",
            args.enable_password_env,
            required=False,
        ),
    )


def _secret_arg(
    value: str | None,
    from_stdin: bool,
    prompt: str,
    env_name: str | None = None,
    required: bool = True,
) -> str | None:
    sources = int(value is not None) + int(from_stdin) + int(env_name is not None)
    if sources > 1:
        raise SystemExit(f"Use only one source for {prompt.lower()}: argument, stdin, or environment variable")
    if value is not None:
        return value
    if env_name:
        secret = os.getenv(env_name)
        if secret is None:
            raise SystemExit(f"Environment variable {env_name!r} is not set")
        return secret
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    if not required:
        return None
    return getpass.getpass(f"{prompt}: ")


def _limit(devices: list, limit: int | None) -> list:
    if limit is not None and limit < 1:
        raise SystemExit("--limit must be >= 1")
    return devices if limit is None else devices[:limit]


def _add_connection_args(parser: argparse.ArgumentParser, require_login: bool = True) -> None:
    parser.add_argument("--login", required=require_login)
    parser.add_argument("--password")
    parser.add_argument("--password-stdin", action="store_true")
    parser.add_argument("--password-env")
    parser.add_argument("--enable-password")
    parser.add_argument("--enable-password-stdin", action="store_true")
    parser.add_argument("--enable-password-env")
    parser.add_argument("--transport", choices=TRANSPORT_CHOICES, default="auto")
    parser.add_argument("--ssh-port", type=int, default=22)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--read-timeout", type=float, default=120.0)


def _add_plan_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--show-secrets", action="store_true")


def _parse_acl_rule(value: str) -> AclRule:
    parts = [part.strip() for part in value.split(",", 5)]
    if len(parts) < 5:
        raise argparse.ArgumentTypeError("ACL rule must have at least 5 comma-separated fields")
    return AclRule(
        sequence=int(parts[0]),
        action=parts[1],
        protocol=parts[2],
        source=parts[3],
        destination=parts[4],
        extra=parts[5] if len(parts) > 5 else "",
    )


def _emit_plans(plans: list[CommandPlan], args: argparse.Namespace) -> None:
    redact = not args.show_secrets
    if args.json_output:
        write_plans(args.json_output, plans, redact_secrets=redact)
    if args.format == "json":
        print(json.dumps(plans_to_dict(plans, redact_secrets=redact), ensure_ascii=False, indent=2))
    else:
        _print_plans(plans, show_secrets=args.show_secrets)


def _print_plans(plans: list[CommandPlan], show_secrets: bool = False) -> None:
    for plan in plans:
        transport = selected_transport_label(plan)
        print(
            f"=== {plan.device.ip_address} {plan.device.vendor} {plan.device.model} "
            f"[{plan.driver} via {transport}] ==="
        )
        for warning in plan.warnings:
            print(f"warning: {warning}")
        for step in plan.execution_steps:
            command = step.command if show_secrets or not step.secret else "<redacted>"
            print(f"{step.phase.value}: {command}")


if __name__ == "__main__":
    main()
