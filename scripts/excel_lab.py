from __future__ import annotations

"""Excel-first file-based lab prototype CLI.

This is the primary operator path for running SwitchFleet from an Excel
inventory without PostgreSQL, Alembic, FastAPI, or SQLAlchemy setup.
Enterprise DB/API mode remains available through the application package and
the DB-backed ``scripts/lab_prototype.py`` helper.
"""

import argparse
import getpass
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.core.vendor_driver_contracts import VendorOperation, get_vendor_driver_contract
from app.services.driver_capability_matrix import DriverCapabilityMatrix
from app.services.excel_inventory import ExcelInventoryDevice, load_excel_inventory, resolve_excel_device
from app.services.excel_lab_runtime import ExcelLabApplyExecutor, ExcelLabBackupRunner
from app.services.excel_lab_safety import ExcelLabSafetyRequest, ExcelLabSafetyService
from app.services.file_credential_vault import FileCredentialVault
from app.services.file_lab_state import FileLabState
from app.services.vendor_command_templates import VendorCommandTemplateService, command_hash


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="excel-lab", description="Excel-first SwitchFleet lab prototype helper.")
    parser.add_argument("--state-dir", default=".switchfleet_lab")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("inventory_path", type=Path, nargs="?")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("doctor", help="Check Excel lab runtime prerequisites")
    list_parser = sub.add_parser("list", help="List Excel inventory devices with runtime decisions")
    list_parser.add_argument("--vendor")
    list_parser.add_argument("--category")
    list_parser.add_argument("--status")
    list_parser.add_argument("--allowlisted-only", action="store_true")
    list_parser.add_argument("--limit", type=int)

    device_parser = sub.add_parser("check-runtime", help="Show runtime decision for one Excel device")
    device_parser.add_argument("--device", required=True)

    add_credential = sub.add_parser("add-credential", help="Create encrypted file credential ref")
    add_credential.add_argument("--name", required=True)
    add_credential.add_argument("--username", required=True)
    add_credential.add_argument("--password-prompt", action="store_true")
    add_credential.add_argument("--password-env")
    add_credential.add_argument("--purpose", default="lab_apply")

    backup = sub.add_parser("backup", help="Run read-only lab backup for an allowlisted Excel device")
    backup.add_argument("--device", required=True)
    backup.add_argument("--credential", required=True)

    dry_run = sub.add_parser("dry-run", help="Render redacted command plan and store dry-run hash")
    _operation_args(dry_run)

    evaluate = sub.add_parser("evaluate-apply", help="Evaluate file-mode lab apply safety gates")
    _apply_args(evaluate)

    execute = sub.add_parser("execute-apply", help="Execute fake or real lab apply after file-mode gates pass")
    _apply_args(execute)
    execute.add_argument("--real-lab", action="store_true")

    audit = sub.add_parser("audit-tail", help="Show file-mode audit tail")
    audit.add_argument("--limit", type=int, default=20)

    certify = sub.add_parser("certify", help="Record lab-only capability certification evidence")
    certify.add_argument("--device", required=True)
    certify.add_argument("--capability", required=True)
    certify.add_argument("--credential", required=True)

    sub.add_parser("certification-report", help="Show lab certification records")

    args = parser.parse_args(argv)
    if args.command is None or args.inventory_path is None:
        parser.print_help()
        raise SystemExit(0 if args.command is None else 2)
    try:
        result = _dispatch(args)
    except Exception as exc:
        if args.debug:
            raise
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    state = FileLabState(args.state_dir)
    devices = load_excel_inventory(args.inventory_path)
    if args.command == "doctor":
        return _doctor(args, state, devices)
    if args.command == "list":
        return {"devices": _list_devices(devices, args)}
    if args.command == "check-runtime":
        device = resolve_excel_device(devices, args.device)
        return {"device": _device_dict(device), "runtime_decision": _runtime_decision(device)}
    if args.command == "add-credential":
        vault = _vault(state)
        secret = _read_secret(args)
        metadata = vault.create_or_update(name=args.name, username=args.username, secret=secret, purpose=args.purpose)
        return {"credential": metadata.to_safe_dict()}
    if args.command == "backup":
        device = resolve_excel_device(devices, args.device)
        result = ExcelLabBackupRunner(state, _vault(state)).backup_device(device, credential_ref=args.credential)
        return {"backup": result.to_dict()}
    if args.command == "dry-run":
        device = resolve_excel_device(devices, args.device)
        operation = VendorOperation(args.operation)
        parameters = _command_parameters(args)
        commands = _render(device, operation, parameters)
        hash_value = command_hash(commands)
        state.save_dry_run(
            {
                "device_id": device.id,
                "device_label": device.label,
                "operation": operation.value,
                "command_hash": hash_value,
                "commands": [command.to_safe_dict() for command in commands],
            }
        )
        return {
            "device": _device_dict(device),
            "operation": operation.value,
            "commands": [command.to_safe_dict() for command in commands],
            "command_hash": hash_value,
        }
    if args.command == "evaluate-apply":
        decision, _transport_decision = _evaluate(state, devices, args, require_real_apply=False)
        return decision.to_dict()
    if args.command == "execute-apply":
        if args.real_lab and not args.simulation_hash:
            raise SystemExit("Real lab execution requires --simulation-hash from a prior dry-run")
        decision, transport_decision = _evaluate(state, devices, args, require_real_apply=args.real_lab)
        device = resolve_excel_device(devices, args.device)
        result = ExcelLabApplyExecutor(state, _vault(state)).execute(
            device=device,
            safety_decision=decision,
            transport_decision=transport_decision,
            credential_ref=args.credential,
            real_lab=args.real_lab,
        )
        return {"decision": decision.to_dict(), "execution": result.to_dict()}
    if args.command == "audit-tail":
        return {"events": state.audit_tail(args.limit)}
    if args.command == "certify":
        device = resolve_excel_device(devices, args.device)
        _vault(state).get_metadata(args.credential)
        _assert_allowlisted(device)
        record = state.save_lab_validation(
            {
                "device_id": device.id,
                "device_label": device.label,
                "ip_address": device.ip_address,
                "vendor": device.vendor,
                "model": device.model,
                "driver_name": device.driver_name,
                "capability": args.capability,
                "production_certified": False,
                "evidence": "Excel lab operator certification record; validate on real firmware before production use.",
            }
        )
        state.append_audit(
            action="excel_lab.certified",
            actor="excel-lab",
            object_type="lab_validation",
            object_id=record["id"],
            metadata={"device_id": device.id, "capability": args.capability},
        )
        return {"certification": record}
    if args.command == "certification-report":
        return {"certifications": state.read_lab_validations()}
    raise SystemExit(f"Unsupported command: {args.command}")


def _operation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--device", required=True)
    parser.add_argument("--operation", choices=[item.value for item in VendorOperation], required=True)
    parser.add_argument("--vlan-id", type=int)
    parser.add_argument("--name")
    parser.add_argument("--username")
    parser.add_argument("--new-password-prompt", action="store_true")
    parser.add_argument("--new-password-env")
    parser.add_argument("--level", type=int, default=15)
    parser.add_argument("--interface")


def _apply_args(parser: argparse.ArgumentParser) -> None:
    _operation_args(parser)
    parser.add_argument("--credential", required=True)
    parser.add_argument("--simulation-hash")


def _doctor(args: argparse.Namespace, state: FileLabState, devices: list[ExcelInventoryDevice]) -> dict[str, Any]:
    settings = get_settings()
    return {
        "excel_readable": True,
        "required_columns_valid": True,
        "device_count": len(devices),
        "state_dir": str(state.paths.root),
        "state_dir_ok": state.paths.root.exists(),
        "secret_key_configured": bool(settings.secret_key),
        "lab_device_allowlist_configured": bool(settings.lab_device_allowlist),
        "production_apply_enabled": settings.production_real_apply_enabled,
        "database_required": False,
        "alembic_required": False,
        "netmiko_available": importlib.util.find_spec("netmiko") is not None,
        "paramiko_available": importlib.util.find_spec("paramiko") is not None,
    }


def _list_devices(devices: list[ExcelInventoryDevice], args: argparse.Namespace) -> list[dict[str, Any]]:
    filtered = []
    for device in devices:
        if args.vendor and args.vendor.casefold() not in device.vendor.casefold():
            continue
        if args.category and args.category.casefold() not in (device.category or "").casefold():
            continue
        if args.status and args.status.casefold() not in (device.status or "").casefold():
            continue
        if args.allowlisted_only and not _is_allowlisted(device):
            continue
        filtered.append({**_device_dict(device), "runtime": _runtime_decision(device), "lab_allowed": _is_allowlisted(device)})
    return filtered[: args.limit] if args.limit else filtered


def _evaluate(
    state: FileLabState,
    devices: list[ExcelInventoryDevice],
    args: argparse.Namespace,
    *,
    require_real_apply: bool,
):
    device = resolve_excel_device(devices, args.device)
    service = ExcelLabSafetyService(state, _vault(state), settings=get_settings())
    return service.evaluate(
        ExcelLabSafetyRequest(
            device=device,
            operation=VendorOperation(args.operation),
            credential_ref=args.credential,
            command_parameters=_command_parameters(args),
            simulation_hash=args.simulation_hash,
            require_real_apply=require_real_apply,
        )
    )


def _render(device: ExcelInventoryDevice, operation: VendorOperation, parameters: dict[str, Any]):
    decision = DriverCapabilityMatrix().decide(
        vendor=device.vendor,
        model=device.model,
        platform=device.platform,
        driver_name=device.driver_name,
        device_id=device.id,
        hostname=device.hostname,
    )
    return VendorCommandTemplateService().render(decision.family, operation, parameters)


def _runtime_decision(device: ExcelInventoryDevice) -> dict[str, Any]:
    decision = DriverCapabilityMatrix().decide(
        vendor=device.vendor,
        model=device.model,
        platform=device.platform,
        driver_name=device.driver_name,
        device_id=device.id,
        hostname=device.hostname,
    )
    contract = get_vendor_driver_contract(decision.family)
    data = decision.to_safe_dict()
    data["apply_support_level"] = contract.apply_support_level.value
    data["production_certified"] = contract.production_certified
    return data


def _command_parameters(args: argparse.Namespace) -> dict[str, Any]:
    operation = VendorOperation(str(args.operation))
    if operation == VendorOperation.vlan_create:
        return {"vlan_id": args.vlan_id, "name": args.name}
    if operation == VendorOperation.password_change:
        return {"username": args.username, "password": _read_new_password(args), "level": args.level}
    if operation == VendorOperation.vlan_assign_port:
        return {"interface": args.interface, "vlan_id": args.vlan_id}
    return {}


def _vault(state: FileLabState) -> FileCredentialVault:
    return FileCredentialVault(state)


def _read_secret(args: argparse.Namespace) -> str:
    if args.password_env:
        value = os.getenv(args.password_env)
        if value is None:
            raise SystemExit(f"Environment variable {args.password_env!r} is not set")
        return value
    if args.password_prompt:
        return getpass.getpass("Credential password: ")
    raise SystemExit("Use --password-prompt or --password-env; plaintext password arguments are intentionally unsupported")


def _read_new_password(args: argparse.Namespace) -> str:
    if args.new_password_env:
        value = os.getenv(args.new_password_env)
        if value is None:
            raise SystemExit(f"Environment variable {args.new_password_env!r} is not set")
        return value
    if args.new_password_prompt:
        return getpass.getpass("New password: ")
    raise SystemExit("Password operations require --new-password-prompt or --new-password-env")


def _assert_allowlisted(device: ExcelInventoryDevice) -> None:
    if not _is_allowlisted(device):
        raise SystemExit(f"Device {device.label} / {device.ip_address} is not in NCP_LAB_DEVICE_ALLOWLIST")


def _is_allowlisted(device: ExcelInventoryDevice) -> bool:
    allowlist = {item.strip() for item in get_settings().lab_device_allowlist.split(",") if item.strip()}
    identifiers = {device.id, device.label, device.hostname, device.ip_address}
    return bool(allowlist & identifiers)


def _device_dict(device: ExcelInventoryDevice) -> dict[str, Any]:
    return {
        "id": device.id,
        "label": device.label,
        "hostname": device.hostname,
        "ip_address": device.ip_address,
        "vendor": device.vendor,
        "model": device.model,
        "category": device.category,
        "status": device.status,
        "location": device.location,
        "contact": device.contact,
        "driver_name": device.driver_name,
        "platform": device.platform,
    }


if __name__ == "__main__":
    main(sys.argv[1:])
