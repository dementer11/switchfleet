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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.core.vendor_driver_contracts import VendorOperation, get_vendor_driver_contract
from app.services.driver_capability_matrix import DriverCapabilityMatrix
from app.services.excel_inventory import ExcelDeviceResolution, ExcelInventoryDevice, load_excel_inventory, resolve_excel_device_selector
from app.services.excel_lab_runtime import ExcelLabApplyExecutor, ExcelLabBackupRunner
from app.services.excel_lab_safety import ExcelLabSafetyRequest, ExcelLabSafetyService
from app.services.file_credential_vault import FileCredentialVault
from app.services.file_lab_state import FileLabState
from app.services.vendor_command_templates import VendorCommandTemplateService, command_hash, private_command_hash


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="switchfleet", description="Excel-first SwitchFleet local admin CLI.")
    parser.add_argument("--state-dir", default=".switchfleet_lab")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("inventory_path", type=Path, nargs="?")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("doctor", help="Check Excel lab runtime prerequisites")
    sub.add_parser("summary", help="Summarize Excel inventory, runtime support, backups, and apply readiness")
    list_parser = sub.add_parser("list", help="List Excel inventory devices with runtime decisions")
    list_parser.add_argument("--vendor")
    list_parser.add_argument("--category")
    list_parser.add_argument("--status")
    list_parser.add_argument("--allowlisted-only", action="store_true")
    list_parser.add_argument("--limit", type=int)

    device_parser = sub.add_parser("check-runtime", help="Show runtime decision for one Excel device")
    _device_selector_arg(device_parser)

    add_credential = sub.add_parser("add-credential", help="Create encrypted file credential ref")
    add_credential.add_argument("--name", required=True)
    add_credential.add_argument("--username", required=True)
    add_credential.add_argument("--password-prompt", action="store_true")
    add_credential.add_argument("--password-env")
    add_credential.add_argument("--purpose", default="lab_apply")

    backup = sub.add_parser("backup", help="Run read-only lab backup for an allowlisted Excel device")
    _device_selector_arg(backup)
    backup.add_argument("--credential", required=True)

    dry_run = sub.add_parser("dry-run", help="Render redacted command plan and store dry-run hash")
    _operation_args(dry_run)

    evaluate = sub.add_parser("evaluate-apply", help="Evaluate file-mode lab apply safety gates")
    _apply_args(evaluate)

    certify = sub.add_parser("certify", help="Record lab-only capability certification evidence")
    _device_selector_arg(certify)
    certify.add_argument("--capability", required=True)
    certify.add_argument("--credential", required=True)

    sub.add_parser("certification-report", help="Show lab certification records")

    execute = sub.add_parser("execute-apply", help="Execute fake or real lab apply after file-mode gates pass")
    _apply_args(execute)
    execute.add_argument("--real-lab", action="store_true")

    audit = sub.add_parser("audit-tail", help="Show file-mode audit tail")
    audit.add_argument("--limit", type=int, default=20)

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
    if args.command == "summary":
        return _summary(state, devices)
    if args.command == "list":
        return {"devices": _list_devices(devices, args)}
    if args.command == "check-runtime":
        resolution = _resolve_device(devices, args)
        return _with_selector_warning(_check_runtime(state, resolution.device, args, resolution), resolution)
    if args.command == "add-credential":
        vault = _vault(state)
        secret = _read_secret(args)
        metadata = vault.create_or_update(name=args.name, username=args.username, secret=secret, purpose=args.purpose)
        return {"credential": metadata.to_safe_dict()}
    if args.command == "backup":
        resolution = _resolve_device(devices, args)
        device = resolution.device
        result = ExcelLabBackupRunner(state, _vault(state)).backup_device(device, credential_ref=args.credential)
        return _with_selector_warning({"backup": result.to_dict()}, resolution)
    if args.command == "dry-run":
        resolution = _resolve_device(devices, args)
        device = resolution.device
        operation = VendorOperation(args.operation)
        parameters = _command_parameters(args)
        commands = _render(device, operation, parameters)
        hash_value = command_hash(commands)
        state.save_dry_run(
            {
                "device_id": device.id,
                "internal_device_id": device.id,
                "device_ip": device.ip_address,
                "device_label": device.label,
                "hostname": device.hostname,
                "vendor": device.vendor,
                "model": device.model,
                "operation": operation.value,
                "command_hash": hash_value,
                "private_command_hash": _private_command_hash(commands),
                "commands": [command.to_safe_dict() for command in commands],
            }
        )
        return _with_selector_warning(
            {
                "device_ip": device.ip_address,
                "device": _device_dict(device, debug=args.debug),
                "operation": operation.value,
                "commands": [command.to_safe_dict() for command in commands],
                "command_hash": hash_value,
            },
            resolution,
        )
    if args.command == "evaluate-apply":
        resolution = _resolve_device(devices, args)
        decision, _transport_decision = _evaluate(state, resolution.device, args, require_real_apply=False, record_evaluation=True)
        return _with_selector_warning(
            _with_device_context(_public_safety_decision(decision.to_dict(), resolution.device, debug=args.debug), resolution.device, args),
            resolution,
        )
    if args.command == "certify":
        resolution = _resolve_device(devices, args)
        device = resolution.device
        capability = _certification_capability(args.capability)
        _assert_certification_allowed(state, device, capability, args.credential)
        decision = _decision_for_device(device)
        record = state.save_lab_validation(
            {
                "device_id": device.id,
                "internal_device_id": device.id,
                "device_ip": device.ip_address,
                "device_label": device.label,
                "hostname": device.hostname,
                "vendor": device.vendor,
                "model": device.model,
                "driver_name": device.driver_name,
                "platform": device.platform,
                "family": decision.family.value,
                "selected_transport": decision.selected_transport.value,
                "capability": capability.value,
                "production_certified": False,
                "evidence": "Excel lab operator certification record; validate on real firmware before production use.",
            }
        )
        state.append_audit(
            action="excel_lab.certified",
            actor="excel-lab",
            object_type="lab_validation",
            object_id=record["id"],
            metadata=_device_metadata(device) | {"capability": capability.value},
        )
        return _with_selector_warning(
            _with_device_context({"certification": _public_state_record(record, devices, debug=args.debug)}, device, args),
            resolution,
        )
    if args.command == "certification-report":
        return {"certifications": [_public_state_record(record, devices, debug=args.debug) for record in state.read_lab_validations()]}
    if args.command == "execute-apply":
        if args.real_lab and not args.simulation_hash:
            raise SystemExit("Real lab execution requires --simulation-hash from a prior dry-run")
        resolution = _resolve_device(devices, args)
        device = resolution.device
        decision, transport_decision = _evaluate(state, device, args, require_real_apply=args.real_lab)
        result = ExcelLabApplyExecutor(state, _vault(state)).execute(
            device=device,
            safety_decision=decision,
            transport_decision=transport_decision,
            credential_ref=args.credential,
            real_lab=args.real_lab,
        )
        return _with_selector_warning(
            _with_device_context(
                {"decision": _public_safety_decision(decision.to_dict(), device, debug=args.debug), "execution": result.to_dict()},
                device,
                args,
            ),
            resolution,
        )
    if args.command == "audit-tail":
        return {"events": [_public_audit_event(event, devices, debug=args.debug) for event in state.audit_tail(args.limit)]}
    raise SystemExit(f"Unsupported command: {args.command}")


def _operation_args(parser: argparse.ArgumentParser) -> None:
    _device_selector_arg(parser)
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


def _device_selector_arg(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--device",
        dest="device",
        metavar="IP_ADDRESS",
        help="device IP address; internal excel-* IDs are deprecated for CLI use",
    )
    group.add_argument("--ip", dest="device", metavar="IP_ADDRESS", help="device IP address")


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


def _summary(state: FileLabState, devices: list[ExcelInventoryDevice]) -> dict[str, Any]:
    vendors: dict[str, int] = {}
    models: dict[str, int] = {}
    families: dict[str, int] = {}
    transports: dict[str, int] = {}
    backup_statuses: dict[str, int] = {}
    apply_statuses: dict[str, int] = {}
    allowlisted = 0
    for device in devices:
        report = _runtime_report(state, device)
        vendor = device.normalized_vendor or device.vendor
        model = device.normalized_model or device.model
        family = str(report["family"])
        transport = str(report["transport"])
        backup_status = str(report["backup_status"]["status"])
        apply_status = str(report["apply_status"]["status"])
        vendors[vendor] = vendors.get(vendor, 0) + 1
        models[model] = models.get(model, 0) + 1
        families[family] = families.get(family, 0) + 1
        transports[transport] = transports.get(transport, 0) + 1
        backup_statuses[backup_status] = backup_statuses.get(backup_status, 0) + 1
        apply_statuses[apply_status] = apply_statuses.get(apply_status, 0) + 1
        if _is_allowlisted(device):
            allowlisted += 1
    return {
        "device_count": len(devices),
        "allowlisted_count": allowlisted,
        "vendors": dict(sorted(vendors.items())),
        "models": dict(sorted(models.items())),
        "families": dict(sorted(families.items())),
        "transports": dict(sorted(transports.items())),
        "backup_statuses": dict(sorted(backup_statuses.items())),
        "apply_statuses": dict(sorted(apply_statuses.items())),
        "unsupported_count": apply_statuses.get("unsupported", 0),
        "blocked_count": apply_statuses.get("blocked_until_certified", 0),
        "candidate_count": apply_statuses.get("candidate_gated", 0),
        "database_required": False,
        "production_apply_enabled": get_settings().production_real_apply_enabled,
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
        report = _runtime_report(None, device, debug=args.debug)
        filtered.append(
            {
                **_device_dict(device, debug=args.debug),
                "family": report["family"],
                "driver": report["driver"],
                "selected_transport": report["transport"],
                "backup_supported": report["backup_status"]["status"] != "unsupported",
                "backup_status": report["backup_status"]["status"],
                "apply_support_level": report["apply_status"]["apply_support_level"],
                "apply_status": report["apply_status"]["status"],
                "lab_allowed": _is_allowlisted(device),
                "reasons": report["reasons"],
                "warnings": report["warnings"],
                **({"runtime_decision": report["decision"]} if args.debug else {}),
            }
        )
    return filtered[: args.limit] if args.limit else filtered


def _evaluate(
    state: FileLabState,
    device: ExcelInventoryDevice,
    args: argparse.Namespace,
    *,
    require_real_apply: bool,
    record_evaluation: bool = False,
):
    operation = VendorOperation(args.operation)
    parameters = _command_parameters(args)
    service = ExcelLabSafetyService(state, _vault(state), settings=get_settings())
    decision, transport_decision = service.evaluate(
        ExcelLabSafetyRequest(
            device=device,
            operation=operation,
            credential_ref=args.credential,
            command_parameters=parameters,
            simulation_hash=args.simulation_hash,
            require_real_apply=require_real_apply,
        )
    )
    if record_evaluation:
        dry_run = state.get_dry_run(args.simulation_hash or "", device_id=device.id, operation=operation.value) if args.simulation_hash else None
        state.save_evaluation(
            {
                "device_id": device.id,
                "internal_device_id": device.id,
                "device_ip": device.ip_address,
                "device_label": device.label,
                "hostname": device.hostname,
                "operation": operation.value,
                "credential_ref": args.credential,
                "simulation_hash": args.simulation_hash,
                "command_hash": decision.command_hash,
                "private_command_hash": (dry_run or {}).get("private_command_hash"),
                "vendor": device.vendor,
                "model": device.model,
                "driver_name": device.driver_name,
                "platform": device.platform,
                "allowed": decision.allowed,
                "satisfied_gates": decision.satisfied_gates,
                "denied_gates": decision.denied_gates,
                "reasons": decision.reasons,
                "warnings": decision.warnings,
                "driver_family": decision.driver_family,
                "selected_transport": decision.selected_transport,
                "real_apply_requested": decision.real_apply_requested,
            }
        )
    return decision, transport_decision


def _render(device: ExcelInventoryDevice, operation: VendorOperation, parameters: dict[str, Any]):
    decision = _decision_for_device(device)
    return VendorCommandTemplateService().render(decision.family, operation, parameters)


def _private_command_hash(commands: list[Any]) -> str:
    return private_command_hash(commands, secret_key=get_settings().secret_key)


def _decision_for_device(device: ExcelInventoryDevice):
    decision = DriverCapabilityMatrix().decide(
        vendor=device.vendor,
        model=device.model,
        platform=device.platform,
        driver_name=device.driver_name,
        device_id=device.id,
        hostname=device.hostname,
    )
    return decision


def _check_runtime(
    state: FileLabState,
    device: ExcelInventoryDevice,
    args: argparse.Namespace,
    resolution: ExcelDeviceResolution,
) -> dict[str, Any]:
    report = _runtime_report(state, device, debug=args.debug)
    return {
        "selector_used": resolution.selector_used,
        "device_ip": device.ip_address,
        "hostname": device.hostname,
        "label": device.label,
        "vendor": device.vendor,
        "model": device.model,
        "device": _device_dict(device, debug=args.debug),
        "original_vendor": device.original_vendor or device.vendor,
        "original_model": device.original_model or device.model,
        "normalized_vendor": device.normalized_vendor or device.vendor,
        "normalized_model": device.normalized_model or device.model,
        "family": report["family"],
        "driver": report["driver"],
        "platform": device.platform,
        "selected_transport": report["transport"],
        "transport": report["transport"],
        "backup_status": report["backup_status"],
        "apply_status": report["apply_status"],
        "reasons": report["reasons"],
        "warnings": report["warnings"],
        "runtime_decision": report["decision"],
    }


def _runtime_report(state: FileLabState | None, device: ExcelInventoryDevice, *, debug: bool = False) -> dict[str, Any]:
    decision = _decision_for_device(device)
    contract = get_vendor_driver_contract(decision.family)
    data = _public_runtime_decision(decision.to_safe_dict(), device, debug=debug)
    data["apply_support_level"] = contract.apply_support_level.value
    data["production_certified"] = contract.production_certified
    backup = _backup_status(state, device, decision, contract.read_only_commands)
    apply_status = _apply_status(decision, contract.apply_support_level.value)
    return {
        "family": decision.family.value,
        "driver": decision.driver_name,
        "transport": decision.selected_transport.value,
        "backup_status": backup,
        "apply_status": apply_status,
        "reasons": backup["reasons"] + apply_status["reasons"],
        "warnings": list(decision.safety_warnings),
        "decision": data,
    }


def _backup_status(
    state: FileLabState | None,
    device: ExcelInventoryDevice,
    decision: Any,
    read_only_commands: tuple[str, ...],
) -> dict[str, Any]:
    reasons: list[str] = []
    if decision.selected_transport.value in {"unsupported", "icmp_only"} or not read_only_commands:
        reasons.append(f"{decision.family.value} has no CLI backup path in Excel lab mode")
        return {"status": "unsupported", "latest_backup_id": None, "required_before_apply": True, "reasons": reasons}
    latest = state.latest_backup_for(device.id) if state is not None else None
    if latest:
        if not _backup_is_fresh(latest):
            return {
                "status": "stale",
                "latest_backup_id": latest.get("id"),
                "required_before_apply": True,
                "reasons": [f"A sanitized backup newer than {_backup_max_age_hours()} hours is required before lab apply."],
            }
        return {"status": "present", "latest_backup_id": latest.get("id"), "required_before_apply": True, "reasons": []}
    return {
        "status": "missing",
        "latest_backup_id": None,
        "required_before_apply": True,
        "reasons": ["A sanitized backup is required before any lab config apply."],
    }


def _backup_is_fresh(backup: dict[str, Any]) -> bool:
    try:
        created_at = datetime.fromisoformat(str(backup.get("created_at") or ""))
    except ValueError:
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - created_at <= timedelta(hours=_backup_max_age_hours())


def _backup_max_age_hours() -> int:
    return max(1, int(get_settings().lab_backup_max_age_hours))


def _apply_status(decision: Any, apply_support_level: str) -> dict[str, Any]:
    reasons = ["config_apply_allowed is false globally; dry-run/evaluate gates are mandatory."]
    if decision.family.value in {"unknown", "icmp", "generic_ssh", "limited_web", "non_switch"}:
        status = "unsupported"
        reasons.append(f"{decision.family.value} cannot config apply in Excel lab mode.")
    elif decision.family.value in {"qtech", "eltex", "bulat"}:
        status = "blocked_until_certified"
        reasons.append(f"{decision.family.value} config apply is blocked until explicit certified templates exist.")
    else:
        status = "candidate_gated"
        reasons.append("Candidate device requires backup, stored dry-run hash, lab validation, allowlist, credential ref, and execute gates.")
    return {
        "status": status,
        "apply_support_level": apply_support_level,
        "config_apply_allowed": False,
        "production_allowed": False,
        "requires_backup": True,
        "requires_dry_run": True,
        "reasons": reasons,
    }


def _command_parameters(args: argparse.Namespace) -> dict[str, Any]:
    operation = VendorOperation(str(args.operation))
    if operation == VendorOperation.vlan_create:
        return {"vlan_id": args.vlan_id, "name": args.name}
    if operation == VendorOperation.password_change:
        return {"username": args.username, "password": _read_new_password(args), "level": args.level}
    if operation == VendorOperation.vlan_assign_port:
        return {"interface": args.interface, "vlan_id": args.vlan_id}
    return {}


def _certification_capability(value: str) -> VendorOperation:
    normalized = value.strip().casefold().replace("-", "_")
    if normalized == "backup":
        normalized = VendorOperation.read_backup.value
    try:
        return VendorOperation(normalized)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in VendorOperation)
        raise SystemExit(f"Unsupported certification capability {value!r}; expected one of: backup, {allowed}") from exc


def _assert_certification_allowed(
    state: FileLabState,
    device: ExcelInventoryDevice,
    capability: VendorOperation,
    credential_ref: str,
) -> None:
    vault = _vault(state)
    usable, reasons = vault.check_usable(credential_ref)
    if not usable:
        raise SystemExit("; ".join(reasons))
    _assert_allowlisted(device)
    decision = _decision_for_device(device)
    contract = get_vendor_driver_contract(decision.family)
    if capability == VendorOperation.read_backup:
        if decision.selected_transport.value in {"unsupported", "icmp_only"} or not contract.read_only_commands:
            raise SystemExit(f"{decision.family.value} cannot be certified for CLI backup in Excel lab mode")
        latest_backup = state.latest_backup_for(device.id)
        if not latest_backup:
            raise SystemExit("A fresh sanitized backup is required before certifying CLI backup")
        if not _backup_is_fresh(latest_backup):
            raise SystemExit(f"A sanitized backup newer than {_backup_max_age_hours()} hours is required before certifying CLI backup")
        return
    blocked_families = {"unknown", "generic_ssh", "icmp", "limited_web", "non_switch", "qtech", "eltex", "bulat"}
    if decision.family.value in blocked_families or decision.selected_transport.value in {"unsupported", "icmp_only"}:
        raise SystemExit(f"{decision.family.value} cannot be certified for config apply in Excel lab mode")
    if not contract.supports_operation(capability) or capability not in contract.config_command_templates:
        raise SystemExit(f"{decision.family.value} has no runnable template for certification capability {capability.value}")
    latest_backup = state.latest_backup_for(device.id)
    if not latest_backup:
        raise SystemExit("A sanitized backup is required before certifying config apply")
    if not _backup_is_fresh(latest_backup):
        raise SystemExit(f"A sanitized backup newer than {_backup_max_age_hours()} hours is required before certifying config apply")
    dry_run = _latest_stored_dry_run(state, device, capability)
    if not dry_run:
        raise SystemExit("A stored dry-run for this device and capability is required before certification")
    if not _has_pre_certification_evaluation(state, device, capability, dry_run, credential_ref, decision):
        raise SystemExit("Run evaluate-apply with the stored dry-run simulation hash before certifying this capability")


def _has_stored_dry_run(state: FileLabState, device: ExcelInventoryDevice, capability: VendorOperation) -> bool:
    return _latest_stored_dry_run(state, device, capability) is not None


def _latest_stored_dry_run(state: FileLabState, device: ExcelInventoryDevice, capability: VendorOperation) -> dict[str, Any] | None:
    matches: list[dict[str, Any]] = []
    for item in state.read_dry_runs():
        if item.get("device_id") != device.id or item.get("operation") != capability.value:
            continue
        if capability == VendorOperation.password_change and not item.get("private_command_hash"):
            continue
        matches.append(item)
    return sorted(matches, key=lambda item: item.get("created_at", ""), reverse=True)[0] if matches else None


def _has_pre_certification_evaluation(
    state: FileLabState,
    device: ExcelInventoryDevice,
    capability: VendorOperation,
    dry_run: dict[str, Any],
    credential_ref: str,
    decision: Any,
) -> bool:
    command_hash = str(dry_run.get("command_hash") or "")
    if not command_hash:
        return False
    evaluation = state.latest_evaluation_for(device.id, capability.value, command_hash)
    if not evaluation:
        return False
    if evaluation.get("credential_ref") != credential_ref:
        return False
    if evaluation.get("vendor") != device.vendor:
        return False
    if evaluation.get("model") != device.model:
        return False
    if evaluation.get("driver_name") != device.driver_name:
        return False
    if evaluation.get("platform") != device.platform:
        return False
    if evaluation.get("driver_family") != decision.family.value:
        return False
    if evaluation.get("selected_transport") != decision.selected_transport.value:
        return False
    if evaluation.get("real_apply_requested") is True:
        return False
    private_hash = dry_run.get("private_command_hash")
    if private_hash and evaluation.get("private_command_hash") != private_hash:
        return False
    denied = set(evaluation.get("denied_gates") or [])
    if evaluation.get("allowed") is True and not denied:
        return True
    return denied == {"lab_validation"}


def _resolve_device(devices: list[ExcelInventoryDevice], args: argparse.Namespace) -> ExcelDeviceResolution:
    return resolve_excel_device_selector(devices, str(args.device))


def _with_selector_warning(payload: dict[str, Any], resolution: ExcelDeviceResolution) -> dict[str, Any]:
    if resolution.warning:
        return {"selector_warning": resolution.warning, **payload}
    return payload


def _with_device_context(payload: dict[str, Any], device: ExcelInventoryDevice, args: argparse.Namespace) -> dict[str, Any]:
    return {"device_ip": device.ip_address, "device": _device_dict(device, debug=args.debug), **payload}


def _device_metadata(device: ExcelInventoryDevice) -> dict[str, Any]:
    return {
        "device_id": device.id,
        "internal_device_id": device.id,
        "device_ip": device.ip_address,
        "device_label": device.label,
        "hostname": device.hostname,
        "vendor": device.vendor,
        "model": device.model,
    }


def _public_runtime_decision(data: dict[str, Any], device: ExcelInventoryDevice, *, debug: bool) -> dict[str, Any]:
    public = dict(data)
    public.pop("device_id", None)
    public["device_ip"] = device.ip_address
    public["hostname"] = device.hostname
    public["label"] = device.label
    if debug:
        public["internal_device_id"] = device.id
    return public


def _public_safety_decision(data: dict[str, Any], device: ExcelInventoryDevice, *, debug: bool) -> dict[str, Any]:
    public = dict(data)
    internal = public.pop("device_id", None)
    public["device_ip"] = device.ip_address
    public.setdefault("hostname", device.hostname)
    public.setdefault("label", device.label)
    public.setdefault("vendor", device.vendor)
    public.setdefault("model", device.model)
    if debug and internal:
        public["internal_device_id"] = internal
    return public


def _public_state_record(record: dict[str, Any], devices: list[ExcelInventoryDevice], *, debug: bool) -> dict[str, Any]:
    public = dict(record)
    device = _device_for_state_record(devices, public)
    if device is not None:
        public.setdefault("device_ip", device.ip_address)
        public.setdefault("hostname", device.hostname)
        public.setdefault("device_label", device.label)
        public.setdefault("vendor", device.vendor)
        public.setdefault("model", device.model)
    internal = public.pop("device_id", None)
    public.pop("ip_address", None)
    if debug and internal:
        public["internal_device_id"] = public.get("internal_device_id") or internal
    elif not debug:
        public.pop("internal_device_id", None)
    return public


def _public_audit_event(event: dict[str, Any], devices: list[ExcelInventoryDevice], *, debug: bool) -> dict[str, Any]:
    public = dict(event)
    metadata = public.get("metadata")
    if isinstance(metadata, dict):
        public["metadata"] = _public_state_record(metadata, devices, debug=debug)
    object_id = public.get("object_id")
    if public.get("object_type") == "device" and isinstance(object_id, str):
        device = _device_by_internal_id(devices, object_id)
        if device is not None:
            public["object_id"] = device.ip_address
            public["device_ip"] = device.ip_address
            if debug:
                public["internal_device_id"] = object_id
    return public


def _device_for_state_record(devices: list[ExcelInventoryDevice], record: dict[str, Any]) -> ExcelInventoryDevice | None:
    ip = record.get("device_ip") or record.get("ip_address")
    if isinstance(ip, str):
        for device in devices:
            if device.ip_address == ip:
                return device
    internal = record.get("device_id") or record.get("internal_device_id")
    if isinstance(internal, str):
        return _device_by_internal_id(devices, internal)
    return None


def _device_by_internal_id(devices: list[ExcelInventoryDevice], internal_device_id: str) -> ExcelInventoryDevice | None:
    for device in devices:
        if device.id == internal_device_id:
            return device
    return None


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
        raise SystemExit(f"Device {device.ip_address} ({device.label}) is not in NCP_LAB_DEVICE_ALLOWLIST")


def _is_allowlisted(device: ExcelInventoryDevice) -> bool:
    allowlist = {item.strip() for item in get_settings().lab_device_allowlist.split(",") if item.strip()}
    return device.ip_address in allowlist


def _device_dict(device: ExcelInventoryDevice, *, debug: bool = False) -> dict[str, Any]:
    data = {
        "device_ip": device.ip_address,
        "ip_address": device.ip_address,
        "hostname": device.hostname,
        "label": device.label,
        "vendor": device.vendor,
        "model": device.model,
        "original_vendor": device.original_vendor or device.vendor,
        "original_model": device.original_model or device.model,
        "normalized_vendor": device.normalized_vendor or device.vendor,
        "normalized_model": device.normalized_model or device.model,
        "category": device.category,
        "status": device.status,
        "location": device.location,
        "contact": device.contact,
        "driver_name": device.driver_name,
        "platform": device.platform,
    }
    if debug:
        data["internal_device_id"] = device.id
    return data


if __name__ == "__main__":
    main(sys.argv[1:])
