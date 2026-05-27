from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .drivers.registry import driver_for
from .inventory import load_inventory
from .models import AccessLevel, AclRule, PortChange, VlanChange
from .orchestrator import acl_plans, apply_plan, backup_config, backup_plans, password_plans, port_plans, vlan_plans
from .transports.ssh_paramiko import ParamikoCliTransport, SshCredentials


def main() -> None:
    parser = argparse.ArgumentParser(prog="netops", description="Network orchestration without Netmiko.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_inventory = sub.add_parser("inventory", help="Inspect inventory and driver mapping")
    p_inventory.add_argument("path", type=Path)

    p_password = sub.add_parser("plan-password", help="Render password change command plans")
    p_password.add_argument("inventory_path", type=Path)
    p_password.add_argument("--username", required=True)
    p_password.add_argument("--new-password", required=True)
    p_password.add_argument("--level", choices=[item.value for item in AccessLevel], default=AccessLevel.admin.value)
    p_password.add_argument("--limit", type=int)

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

    p_vlan = sub.add_parser("plan-vlan", help="Render VLAN command plans")
    p_vlan.add_argument("inventory_path", type=Path)
    p_vlan.add_argument("--vlan-id", type=int, required=True)
    p_vlan.add_argument("--name")
    p_vlan.add_argument("--port", action="append", default=[])
    p_vlan.add_argument("--mode", choices=["access", "trunk"], default="access")
    p_vlan.add_argument("--limit", type=int)

    p_port = sub.add_parser("plan-port", help="Render port command plans")
    p_port.add_argument("inventory_path", type=Path)
    p_port.add_argument("--interface", required=True)
    p_port.add_argument("--description")
    p_port.add_argument("--enabled", choices=["true", "false"])
    p_port.add_argument("--access-vlan", type=int)
    p_port.add_argument("--trunk-vlan", action="append", type=int, default=[])
    p_port.add_argument("--limit", type=int)

    p_backup_plan = sub.add_parser("plan-backup", help="Render running/current-config backup command plans")
    p_backup_plan.add_argument("inventory_path", type=Path)
    p_backup_plan.add_argument("--limit", type=int)

    p_apply = sub.add_parser("apply", help="Apply a password operation over SSH")
    p_apply.add_argument("inventory_path", type=Path)
    p_apply.add_argument("--login", required=True)
    p_apply.add_argument("--password", required=True)
    p_apply.add_argument("--operation", choices=["password"], required=True)
    p_apply.add_argument("--target-user", required=True)
    p_apply.add_argument("--new-password", required=True)
    p_apply.add_argument("--level", choices=[item.value for item in AccessLevel], default=AccessLevel.admin.value)
    p_apply.add_argument("--limit", type=int, default=1)

    p_backup = sub.add_parser("backup", help="Capture device running/current config over SSH")
    p_backup.add_argument("inventory_path", type=Path)
    p_backup.add_argument("--login", required=True)
    p_backup.add_argument("--password", required=True)
    p_backup.add_argument("--output-dir", type=Path, default=Path("backups"))
    p_backup.add_argument("--limit", type=int, default=1)

    args = parser.parse_args()
    if args.command == "inventory":
        _inventory(args.path)
    elif args.command == "plan-password":
        devices = _limit(load_inventory(args.inventory_path), args.limit)
        plans = password_plans(
            devices,
            username=args.username,
            new_password=args.new_password,
            level=AccessLevel(args.level),
        )
        _print_plans(plans)
    elif args.command == "plan-acl":
        devices = _limit(load_inventory(args.inventory_path), args.limit)
        _print_plans(acl_plans(devices, acl_name=args.acl_name, rules=[_parse_acl_rule(r) for r in args.rule]))
    elif args.command == "plan-vlan":
        devices = _limit(load_inventory(args.inventory_path), args.limit)
        change = VlanChange(vlan_id=args.vlan_id, name=args.name, ports=tuple(args.port), mode=args.mode)
        _print_plans(vlan_plans(devices, change))
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
        _print_plans(port_plans(devices, change))
    elif args.command == "plan-backup":
        devices = _limit(load_inventory(args.inventory_path), args.limit)
        _print_plans(backup_plans(devices))
    elif args.command == "apply":
        devices = _limit(load_inventory(args.inventory_path), args.limit)
        plans = password_plans(
            devices,
            username=args.target_user,
            new_password=args.new_password,
            level=AccessLevel(args.level),
        )
        credentials = SshCredentials(username=args.login, password=args.password)
        for plan in plans:
            print(f"applying {plan.operation} to {plan.device.ip_address} with {plan.driver}")
            transport = ParamikoCliTransport(plan.device.ip_address, credentials)
            results = apply_plan(plan, transport)
            failed = any(result.failed for result in results)
            print("failed" if failed else "ok")
    elif args.command == "backup":
        devices = _limit(load_inventory(args.inventory_path), args.limit)
        credentials = SshCredentials(username=args.login, password=args.password)
        for plan in backup_plans(devices):
            if not plan.all_commands:
                print(f"skipping {plan.device.ip_address}: no backup commands for {plan.driver}")
                continue
            print(f"capturing {plan.device.ip_address} with {plan.driver}")
            transport = ParamikoCliTransport(plan.device.ip_address, credentials)
            path = backup_config(plan, transport, args.output_dir)
            print(path if path else "skipped")


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
                "unsupported_backup_devices": unsupported_backup,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _limit(devices: list, limit: int | None) -> list:
    return devices if limit is None else devices[:limit]


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


def _print_plans(plans) -> None:
    for plan in plans:
        print(f"=== {plan.device.ip_address} {plan.device.vendor} {plan.device.model} [{plan.driver}] ===")
        for warning in plan.warnings:
            print(f"warning: {warning}")
        for command in plan.all_commands:
            print(command)


if __name__ == "__main__":
    main()
