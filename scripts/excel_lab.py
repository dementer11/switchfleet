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
from copy import copy
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
from app.services.report_sanitizer import sanitize_report_metadata
from app.services.vendor_command_templates import VendorCommandTemplateService, command_hash, private_command_hash


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="switchfleet", description="Excel-first SwitchFleet local admin CLI.")
    parser.add_argument("--state-dir", default=".switchfleet_lab")
    parser.add_argument("--debug", action="store_true")
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("--json", action="store_true", help="force machine-readable JSON output")
    output_group.add_argument("--human", action="store_true", help="force operator-friendly table/section output")
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

    device_parser = sub.add_parser("check-runtime", help="Show runtime decision for one Excel device or all Excel devices")
    _target_selector_arg(device_parser)

    add_credential = sub.add_parser("add-credential", help="Create encrypted file credential ref")
    add_credential.add_argument("--name", required=True)
    add_credential.add_argument("--username", required=True)
    add_credential.add_argument("--password-prompt", action="store_true")
    add_credential.add_argument("--password-env")
    add_credential.add_argument("--purpose", default="lab_apply")

    backup = sub.add_parser("backup", help="Run read-only lab backup for an allowlisted Excel device")
    _target_selector_arg(backup)
    backup.add_argument("--credential", required=True)

    dry_run = sub.add_parser("dry-run", help="Render redacted command plan and store dry-run hash")
    _operation_args(dry_run)

    evaluate = sub.add_parser("evaluate-apply", help="Evaluate file-mode lab apply safety gates")
    _apply_args(evaluate)

    certify = sub.add_parser("certify", help="Record lab-only capability certification evidence")
    _target_selector_arg(certify)
    certify.add_argument("--capability", required=True)
    certify.add_argument("--credential", required=True)

    sub.add_parser("certification-report", help="Show lab certification records")

    workflow = sub.add_parser("workflow", help="Run profile-driven safe workflow for all Excel devices")
    workflow.add_argument("--profile", type=Path, required=True, help="JSON parameter profile with operation and credential")
    workflow.add_argument(
        "--with-backup",
        action="store_true",
        help="include read-only backup before dry-run/evaluate; requires allowlist and credential",
    )

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
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.human or sys.stdout.isatty():
        print(_format_human_result(args.command, result))
    else:
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
        if args.all:
            return {"devices": [_check_runtime(state, device, args, ExcelDeviceResolution(device, "all")) for device in devices]}
        resolution = _resolve_device(devices, args)
        return _with_selector_warning(_check_runtime(state, resolution.device, args, resolution), resolution)
    if args.command == "add-credential":
        vault = _vault(state)
        secret = _read_secret(args)
        metadata = vault.create_or_update(name=args.name, username=args.username, secret=secret, purpose=args.purpose)
        return {"credential": metadata.to_safe_dict()}
    if args.command == "backup":
        if args.all:
            return {"results": [_run_backup_for_device(state, device, args) for device in devices]}
        resolution = _resolve_device(devices, args)
        result = _run_backup_for_device(state, resolution.device, args)
        if result["status"] != "ok":
            raise SystemExit(result["error"])
        return _with_selector_warning({"backup": result["backup"]}, resolution)
    if args.command == "dry-run":
        if args.all:
            return {"results": [_run_dry_run_for_device(state, device, args) for device in devices]}
        resolution = _resolve_device(devices, args)
        result = _run_dry_run_for_device(state, resolution.device, args)
        if result["status"] != "ok":
            raise SystemExit(result["error"])
        return _with_selector_warning(result["dry_run"], resolution)
    if args.command == "evaluate-apply":
        if args.all:
            return {"results": [_run_evaluate_for_device(state, device, args) for device in devices]}
        resolution = _resolve_device(devices, args)
        decision, _transport_decision = _evaluate_with_latest_hash(state, resolution.device, args, require_real_apply=False, record_evaluation=True)
        return _with_selector_warning(
            _with_device_context(_public_safety_decision(decision.to_dict(), resolution.device, debug=args.debug), resolution.device, args),
            resolution,
        )
    if args.command == "certify":
        if args.all:
            return {"results": [_run_certify_for_device(state, device, args) for device in devices]}
        resolution = _resolve_device(devices, args)
        device = resolution.device
        result = _run_certify_for_device(state, device, args)
        if result["status"] != "ok":
            raise SystemExit(result["error"])
        return _with_selector_warning(
            _with_device_context({"certification": result["certification"]}, device, args),
            resolution,
        )
    if args.command == "certification-report":
        return {"certifications": [_public_state_record(record, devices, debug=args.debug) for record in state.read_lab_validations()]}
    if args.command == "workflow":
        return _run_profile_workflow(state, devices, args)
    if args.command == "execute-apply":
        if args.all:
            if args.real_lab:
                raise SystemExit("Bulk --all real lab execution is intentionally disabled; execute real changes per device.")
            return {"results": [_run_execute_for_device(state, device, args) for device in devices]}
        if args.real_lab and not args.simulation_hash:
            raise SystemExit("Real lab execution requires --simulation-hash from a prior dry-run")
        resolution = _resolve_device(devices, args)
        device = resolution.device
        decision, transport_decision = _evaluate_with_latest_hash(state, device, args, require_real_apply=args.real_lab)
        result = ExcelLabApplyExecutor(state, _vault(state)).execute(
            device=device,
            safety_decision=decision,
            transport_decision=transport_decision,
            credential_ref=_credential_ref(args),
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
    _target_selector_arg(parser)
    parser.add_argument("--profile", type=Path, help="JSON parameter profile with operation and parameters")
    parser.add_argument("--operation", choices=[item.value for item in VendorOperation])
    parser.add_argument("--vlan-id", type=int)
    parser.add_argument("--name")
    parser.add_argument("--username")
    parser.add_argument("--new-password-prompt", action="store_true")
    parser.add_argument("--new-password-env")
    parser.add_argument("--level", type=int, default=15)
    parser.add_argument("--interface")


def _apply_args(parser: argparse.ArgumentParser) -> None:
    _operation_args(parser)
    parser.add_argument("--credential")
    parser.add_argument("--simulation-hash")


def _device_selector_arg(parser: argparse.ArgumentParser) -> None:
    _target_selector_arg(parser, allow_all=False)


def _target_selector_arg(parser: argparse.ArgumentParser, *, allow_all: bool = True) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--device",
        dest="device",
        metavar="IP_ADDRESS",
        help="device IP address; internal excel-* IDs are deprecated for CLI use",
    )
    group.add_argument("--ip", dest="device", metavar="IP_ADDRESS", help="device IP address")
    if allow_all:
        group.add_argument("--all", action="store_true", help="run this command for all Excel inventory devices")


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
    operation = _operation_value(args)
    parameters = _command_parameters(args)
    service = ExcelLabSafetyService(state, _vault(state), settings=get_settings())
    decision, transport_decision = service.evaluate(
        ExcelLabSafetyRequest(
            device=device,
            operation=operation,
            credential_ref=_credential_ref(args),
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
                "credential_ref": _credential_ref(args),
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


def _evaluate_with_latest_hash(
    state: FileLabState,
    device: ExcelInventoryDevice,
    args: argparse.Namespace,
    *,
    require_real_apply: bool,
    record_evaluation: bool = False,
):
    prepared = _args_with_latest_simulation_hash(state, device, args)
    return _evaluate(state, device, prepared, require_real_apply=require_real_apply, record_evaluation=record_evaluation)


def _args_with_latest_simulation_hash(state: FileLabState, device: ExcelInventoryDevice, args: argparse.Namespace) -> argparse.Namespace:
    if getattr(args, "simulation_hash", None):
        return args
    operation = _operation_value(args)
    dry_run = _latest_stored_dry_run(state, device, operation)
    if not dry_run:
        return args
    prepared = copy(args)
    prepared.simulation_hash = dry_run.get("command_hash")
    return prepared


def _run_backup_for_device(state: FileLabState, device: ExcelInventoryDevice, args: argparse.Namespace) -> dict[str, Any]:
    try:
        result = ExcelLabBackupRunner(state, _vault(state)).backup_device(device, credential_ref=_credential_ref(args))
        return {
            "status": "ok",
            "device_ip": device.ip_address,
            "hostname": device.hostname,
            "label": device.label,
            "vendor": device.vendor,
            "model": device.model,
            "backup": result.to_dict(),
        }
    except (Exception, SystemExit) as exc:
        return _failed_device_result(device, exc)


def _run_dry_run_for_device(state: FileLabState, device: ExcelInventoryDevice, args: argparse.Namespace) -> dict[str, Any]:
    try:
        operation = _operation_value(args)
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
        dry_run = {
            "device_ip": device.ip_address,
            "device": _device_dict(device, debug=args.debug),
            "operation": operation.value,
            "commands": [command.to_safe_dict() for command in commands],
            "command_hash": hash_value,
        }
        return {
            "status": "ok",
            "device_ip": device.ip_address,
            "hostname": device.hostname,
            "label": device.label,
            "vendor": device.vendor,
            "model": device.model,
            "operation": operation.value,
            "command_hash": hash_value,
            "dry_run": dry_run,
        }
    except (Exception, SystemExit) as exc:
        return _failed_device_result(device, exc)


def _run_evaluate_for_device(state: FileLabState, device: ExcelInventoryDevice, args: argparse.Namespace) -> dict[str, Any]:
    try:
        prepared = _args_with_latest_simulation_hash(state, device, args)
        decision, _transport_decision = _evaluate(state, device, prepared, require_real_apply=False, record_evaluation=True)
        payload = _public_safety_decision(decision.to_dict(), device, debug=args.debug)
        return {
            "status": "ok",
            "device_ip": device.ip_address,
            "hostname": device.hostname,
            "label": device.label,
            "vendor": device.vendor,
            "model": device.model,
            "operation": _operation_value(args).value,
            "allowed": decision.allowed,
            "command_hash": decision.command_hash,
            "denied_gates": decision.denied_gates,
            "reasons": decision.reasons,
            "decision": _with_device_context(payload, device, args),
        }
    except (Exception, SystemExit) as exc:
        return _failed_device_result(device, exc)


def _run_certify_for_device(state: FileLabState, device: ExcelInventoryDevice, args: argparse.Namespace) -> dict[str, Any]:
    try:
        capability = _certification_capability(args.capability)
        _assert_certification_allowed(state, device, capability, _credential_ref(args))
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
        certification = _public_state_record(record, [device], debug=args.debug)
        return {
            "status": "ok",
            "device_ip": device.ip_address,
            "hostname": device.hostname,
            "label": device.label,
            "vendor": device.vendor,
            "model": device.model,
            "capability": capability.value,
            "certification": certification,
        }
    except (Exception, SystemExit) as exc:
        return _failed_device_result(device, exc)


def _run_execute_for_device(state: FileLabState, device: ExcelInventoryDevice, args: argparse.Namespace) -> dict[str, Any]:
    try:
        prepared = _args_with_latest_simulation_hash(state, device, args)
        decision, transport_decision = _evaluate(state, device, prepared, require_real_apply=False)
        result = ExcelLabApplyExecutor(state, _vault(state)).execute(
            device=device,
            safety_decision=decision,
            transport_decision=transport_decision,
            credential_ref=_credential_ref(args),
            real_lab=False,
        )
        return {
            "status": "ok",
            "device_ip": device.ip_address,
            "hostname": device.hostname,
            "label": device.label,
            "vendor": device.vendor,
            "model": device.model,
            "allowed": decision.allowed,
            "executed": result.executed,
            "execution": result.to_dict(),
        }
    except (Exception, SystemExit) as exc:
        return _failed_device_result(device, exc)


def _run_profile_workflow(state: FileLabState, devices: list[ExcelInventoryDevice], args: argparse.Namespace) -> dict[str, Any]:
    _profile_payload(args)
    profile_operation = _operation_value(args).value
    profile_credential = _credential_ref(args)
    profile_parameters = _command_parameters(args)
    backup_results = [_run_backup_for_device(state, device, args) for device in devices] if args.with_backup else []
    dry_run_results = [_run_dry_run_for_device(state, device, args) for device in devices]
    evaluate_results = [_run_evaluate_for_device(state, device, args) for device in devices]
    rows: list[dict[str, Any]] = []
    backups_by_ip = {item.get("device_ip"): item for item in backup_results}
    dry_runs_by_ip = {item.get("device_ip"): item for item in dry_run_results}
    evaluations_by_ip = {item.get("device_ip"): item for item in evaluate_results}
    for device in devices:
        backup = backups_by_ip.get(device.ip_address)
        dry_run = dry_runs_by_ip.get(device.ip_address)
        evaluation = evaluations_by_ip.get(device.ip_address)
        rows.append(
            {
                "device_ip": device.ip_address,
                "hostname": device.hostname,
                "label": device.label,
                "vendor": device.vendor,
                "model": device.model,
                "backup_status": (backup or {}).get("status") if args.with_backup else "skipped",
                "dry_run_status": (dry_run or {}).get("status"),
                "evaluate_status": (evaluation or {}).get("status"),
                "allowed": (evaluation or {}).get("allowed", False),
                "command_hash": (evaluation or {}).get("command_hash") or (dry_run or {}).get("command_hash"),
                "error": _first_error(backup, dry_run, evaluation),
                "denied_gates": (evaluation or {}).get("denied_gates", []),
                "next_execute_command": _next_execute_command(args, device, evaluation),
            }
        )
    workflow_result = {
        "workflow": {
            "profile": str(args.profile),
            "operation": profile_operation,
            "credential": profile_credential,
            "credential_ref": profile_credential,
            "parameters": _public_parameters(profile_parameters),
            "with_backup": bool(args.with_backup),
            "device_count": len(devices),
            "backup": _stage_counts(backup_results) if args.with_backup else {"skipped": len(devices)},
            "dry_run": _stage_counts(dry_run_results),
            "evaluate": _stage_counts(evaluate_results),
            "allowed_count": sum(1 for item in evaluate_results if item.get("allowed") is True),
            "real_apply_executed": False,
        },
        "results": rows,
    }
    report = state.save_report("workflow", workflow_result, _workflow_markdown_report(workflow_result))
    workflow_result["workflow"]["report"] = report
    return workflow_result


def _first_error(*items: dict[str, Any] | None) -> str:
    for item in items:
        if item and item.get("error"):
            return str(item["error"])
    return ""


def _stage_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in results:
        status = str(item.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _public_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    return sanitize_report_metadata(parameters)


def _next_execute_command(args: argparse.Namespace, device: ExcelInventoryDevice, evaluation: dict[str, Any] | None) -> str:
    if not evaluation or evaluation.get("allowed") is not True:
        return ""
    command_hash = evaluation.get("command_hash")
    if not command_hash:
        return ""
    parts = ["switchfleet"]
    state_dir = getattr(args, "state_dir", None)
    if state_dir is not None:
        parts.extend(["--state-dir", _shell_arg(str(state_dir))])
    parts.extend(
        [
            _shell_arg(str(args.inventory_path)),
            "execute-apply",
            "--device",
            _shell_arg(device.ip_address),
            "--profile",
            _shell_arg(str(args.profile)),
            "--simulation-hash",
            _shell_arg(str(command_hash)),
            "--real-lab",
        ]
    )
    return " ".join(parts)


def _workflow_markdown_report(workflow_result: dict[str, Any]) -> str:
    workflow = workflow_result.get("workflow") or {}
    rows = workflow_result.get("results") or []
    lines = [
        "# SwitchFleet Local Workflow Report",
        "",
        f"- Profile: `{workflow.get('profile')}`",
        f"- Operation: `{workflow.get('operation')}`",
        f"- Credential ref: `{workflow.get('credential_ref') or workflow.get('credential')}`",
        f"- Parameters: `{_inline_counts(workflow.get('parameters'))}`",
        f"- Device count: {workflow.get('device_count')}",
        f"- With backup: {_yes_no(bool(workflow.get('with_backup')))}",
        f"- Allowed count: {workflow.get('allowed_count')}",
        f"- Real apply executed: {_yes_no(bool(workflow.get('real_apply_executed')))}",
        "",
        "## Stage Counts",
        "",
        f"- Backup: {_inline_counts(workflow.get('backup'))}",
        f"- Dry-run: {_inline_counts(workflow.get('dry_run'))}",
        f"- Evaluate: {_inline_counts(workflow.get('evaluate'))}",
        "",
        "## Devices",
        "",
        "| IP | Label | Vendor | Model | Backup | Dry-run | Evaluate | Allowed | Command Hash | Next Execute Command | Error |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                _markdown_cell(row.get(key))
                for key in (
                    "device_ip",
                    "label",
                    "vendor",
                    "model",
                    "backup_status",
                    "dry_run_status",
                    "evaluate_status",
                    "allowed",
                    "command_hash",
                    "next_execute_command",
                    "error",
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- This report is generated from local Excel-first workflow state.",
            "- Production apply remains disabled.",
            "- Bulk real-lab execution is intentionally disabled; execute real changes per device after review.",
        ]
    )
    return "\n".join(lines) + "\n"


def _inline_counts(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return "none"
    return ", ".join(f"{key}={count}" for key, count in value.items())


def _markdown_cell(value: Any) -> str:
    text = _table_value(value)
    return text.replace("|", "\\|")


def _shell_arg(value: str) -> str:
    if not value:
        return '""'
    safe = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/:\\")
    if all(char in safe for char in value):
        return value
    return '"' + value.replace('"', '\\"') + '"'


def _failed_device_result(device: ExcelInventoryDevice, exc: BaseException) -> dict[str, Any]:
    return {
        "status": "failed",
        "device_ip": device.ip_address,
        "hostname": device.hostname,
        "label": device.label,
        "vendor": device.vendor,
        "model": device.model,
        "error": str(exc),
    }


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
    profile = _profile_payload(args)
    profile_parameters = profile.get("parameters") if isinstance(profile.get("parameters"), dict) else {}
    operation = _operation_value(args)
    if operation == VendorOperation.vlan_create:
        return {
            "vlan_id": _arg_or_profile(getattr(args, "vlan_id", None), profile_parameters, "vlan_id"),
            "name": _arg_or_profile(getattr(args, "name", None), profile_parameters, "name"),
        }
    if operation == VendorOperation.password_change:
        return {
            "username": _arg_or_profile(getattr(args, "username", None), profile_parameters, "username"),
            "password": _read_new_password(args),
            "level": _arg_or_profile(getattr(args, "level", None), profile_parameters, "level"),
        }
    if operation == VendorOperation.vlan_assign_port:
        return {
            "interface": _arg_or_profile(getattr(args, "interface", None), profile_parameters, "interface"),
            "vlan_id": _arg_or_profile(getattr(args, "vlan_id", None), profile_parameters, "vlan_id"),
        }
    return {}


def _operation_value(args: argparse.Namespace) -> VendorOperation:
    profile = _profile_payload(args)
    raw = getattr(args, "operation", None) or profile.get("operation")
    if not raw:
        raise SystemExit("Use --operation or provide operation in --profile")
    return VendorOperation(str(raw))


def _credential_ref(args: argparse.Namespace) -> str:
    profile = _profile_payload(args)
    raw = getattr(args, "credential", None) or profile.get("credential") or profile.get("credential_ref")
    if not raw:
        raise SystemExit("Use --credential or provide credential in --profile")
    return str(raw)


def _profile_payload(args: argparse.Namespace) -> dict[str, Any]:
    cached = getattr(args, "_profile_payload", None)
    if isinstance(cached, dict):
        return cached
    profile_path = getattr(args, "profile", None)
    if profile_path is None:
        args._profile_payload = {}
        return args._profile_payload
    path = Path(profile_path)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"Unable to read parameter profile {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Parameter profile {path} is not valid JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise SystemExit(f"Parameter profile {path} must contain a JSON object")
    args._profile_payload = loaded
    return loaded


def _arg_or_profile(value: Any, profile_parameters: dict[str, Any], key: str) -> Any:
    return value if value is not None else profile_parameters.get(key)


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


def _format_human_result(command: str, result: dict[str, Any]) -> str:
    if command == "doctor":
        return _format_key_values(
            "SwitchFleet Local doctor",
            {
                "Excel readable": result.get("excel_readable"),
                "Devices": result.get("device_count"),
                "State dir": result.get("state_dir"),
                "Secret key": _yes_no(bool(result.get("secret_key_configured"))),
                "Allowlist": _yes_no(bool(result.get("lab_device_allowlist_configured"))),
                "Database required": _yes_no(bool(result.get("database_required"))),
                "Alembic required": _yes_no(bool(result.get("alembic_required"))),
                "Netmiko": _available(result.get("netmiko_available")),
                "Paramiko": _available(result.get("paramiko_available")),
                "Production apply": _enabled_disabled(result.get("production_apply_enabled")),
            },
        )
    if command == "summary":
        return "\n\n".join(
            [
                _format_key_values(
                    "SwitchFleet Local summary",
                    {
                        "Devices": result.get("device_count"),
                        "Allowlisted": result.get("allowlisted_count"),
                        "Unsupported": result.get("unsupported_count"),
                        "Blocked": result.get("blocked_count"),
                        "Candidates": result.get("candidate_count"),
                        "Production apply": _enabled_disabled(result.get("production_apply_enabled")),
                    },
                ),
                _format_counts("Vendors", result.get("vendors")),
                _format_counts("Families", result.get("families")),
                _format_counts("Transports", result.get("transports")),
                _format_counts("Backup status", result.get("backup_statuses")),
                _format_counts("Apply status", result.get("apply_statuses")),
            ]
        )
    if command == "list":
        return _format_device_table(result.get("devices") or [])
    if command == "check-runtime":
        if "devices" in result:
            return _format_runtime_table(result["devices"])
        return _format_runtime_details(result)
    if command in {"backup", "dry-run", "evaluate-apply", "certify", "execute-apply"} and "results" in result:
        return _format_bulk_results(command, result["results"])
    if command == "workflow":
        workflow = result.get("workflow") or {}
        report = workflow.get("report") or {}
        return "\n\n".join(
            [
                _format_key_values(
                    "Profile workflow",
                    {
                        "Profile": workflow.get("profile"),
                        "Operation": workflow.get("operation"),
                        "Credential": workflow.get("credential_ref") or workflow.get("credential"),
                        "Parameters": _inline_counts(workflow.get("parameters")),
                        "Devices": workflow.get("device_count"),
                        "With backup": _yes_no(bool(workflow.get("with_backup"))),
                        "Allowed": workflow.get("allowed_count"),
                        "Real apply executed": _yes_no(bool(workflow.get("real_apply_executed"))),
                        "Markdown report": report.get("markdown_path", ""),
                        "JSON report": report.get("json_path", ""),
                    },
                ),
                _format_counts("Backup stage", workflow.get("backup")),
                _format_counts("Dry-run stage", workflow.get("dry_run")),
                _format_counts("Evaluate stage", workflow.get("evaluate")),
                _format_workflow_results(result.get("results") or []),
                _format_next_execute_commands(result.get("results") or []),
            ]
        )
    if command == "backup" and "backup" in result:
        backup = result["backup"]
        return _format_key_values(
            "Backup created",
            {
                "Device IP": backup.get("device_ip"),
                "Hostname": backup.get("hostname"),
                "Label": backup.get("label"),
                "Vendor": backup.get("vendor"),
                "Model": backup.get("model"),
                "Backup ID": backup.get("backup_id"),
                "Transport": backup.get("transport_kind"),
                "Config hash": backup.get("config_hash"),
            },
        )
    if command == "dry-run" and "commands" in result:
        commands = result.get("commands") or []
        command_lines = [f"  {index}. {item.get('command')}" for index, item in enumerate(commands, start=1)]
        return "\n".join(
            [
                _format_key_values(
                    "Dry-run command plan",
                    {
                        "Device IP": result.get("device_ip"),
                        "Operation": result.get("operation"),
                        "Command hash": result.get("command_hash"),
                    },
                ),
                "Commands:",
                *(command_lines or ["  (none)"]),
            ]
        )
    if command == "evaluate-apply":
        return "\n".join(
            [
                _format_key_values(
                    "Apply gate evaluation",
                    {
                        "Device IP": result.get("device_ip"),
                        "Allowed": _yes_no(bool(result.get("allowed"))),
                        "Driver family": result.get("driver_family"),
                        "Transport": result.get("selected_transport"),
                        "Command hash": result.get("command_hash"),
                        "Production allowed": _yes_no(bool(result.get("production_allowed"))),
                    },
                ),
                _format_list("Denied gates", result.get("denied_gates")),
                _format_list("Reasons", result.get("reasons")),
                _format_list("Warnings", result.get("warnings")),
            ]
        )
    if command == "certify" and "certification" in result:
        certification = result["certification"]
        return _format_key_values(
            "Lab certification recorded",
            {
                "Device IP": result.get("device_ip"),
                "Capability": certification.get("capability"),
                "Family": certification.get("family"),
                "Transport": certification.get("selected_transport"),
                "Status": certification.get("status"),
                "Production certified": _yes_no(bool(certification.get("production_certified"))),
            },
        )
    if command == "execute-apply":
        execution = result.get("execution") or {}
        return _format_key_values(
            "Apply execution result",
            {
                "Device IP": result.get("device_ip"),
                "Executed": _yes_no(bool(execution.get("executed"))),
                "Fake transport": _yes_no(bool(execution.get("fake_transport"))),
                "Transport": execution.get("transport_kind"),
                "Command count": execution.get("command_count"),
                "Error": execution.get("error") or "",
            },
        )
    if command == "certification-report":
        rows = result.get("certifications") or []
        return _table(
            ["device_ip", "vendor", "model", "capability", "family", "selected_transport", "status"],
            rows,
            title="Lab certifications",
        )
    if command == "audit-tail":
        rows = result.get("events") or []
        return _table(["created_at", "action", "object_type", "object_id", "device_ip"], rows, title="Audit tail")
    return json.dumps(result, ensure_ascii=False, indent=2)


def _format_key_values(title: str, values: dict[str, Any]) -> str:
    rows = [(key, "" if value is None else str(value)) for key, value in values.items()]
    width = max((len(key) for key, _value in rows), default=0)
    body = "\n".join(f"{key:<{width}} : {value}" for key, value in rows)
    return f"{title}\n{'-' * len(title)}\n{body}"


def _format_counts(title: str, values: Any) -> str:
    if not isinstance(values, dict) or not values:
        return f"{title}: none"
    return _table(["name", "count"], [{"name": key, "count": value} for key, value in values.items()], title=title)


def _format_device_table(devices: list[dict[str, Any]]) -> str:
    return _table(
        [
            "device_ip",
            "label",
            "vendor",
            "model",
            "family",
            "selected_transport",
            "backup_status",
            "apply_status",
            "lab_allowed",
        ],
        devices,
        title="Excel inventory devices",
    )


def _format_runtime_table(devices: list[dict[str, Any]]) -> str:
    rows = [
        {
            "device_ip": item.get("device_ip"),
            "label": item.get("label"),
            "vendor": item.get("vendor"),
            "model": item.get("model"),
            "family": item.get("family"),
            "transport": item.get("selected_transport") or item.get("transport"),
            "backup": (item.get("backup_status") or {}).get("status"),
            "apply": (item.get("apply_status") or {}).get("status"),
        }
        for item in devices
    ]
    return _table(["device_ip", "label", "vendor", "model", "family", "transport", "backup", "apply"], rows, title="Runtime decisions")


def _format_runtime_details(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            _format_key_values(
                "Runtime decision",
                {
                    "Selector": result.get("selector_used"),
                    "Device IP": result.get("device_ip"),
                    "Hostname": result.get("hostname"),
                    "Label": result.get("label"),
                    "Vendor": result.get("vendor"),
                    "Model": result.get("model"),
                    "Family": result.get("family"),
                    "Driver": result.get("driver"),
                    "Platform": result.get("platform"),
                    "Transport": result.get("selected_transport"),
                    "Backup": (result.get("backup_status") or {}).get("status"),
                    "Apply": (result.get("apply_status") or {}).get("status"),
                },
            ),
            _format_list("Reasons", result.get("reasons")),
            _format_list("Warnings", result.get("warnings")),
        ]
    )


def _format_bulk_results(command: str, results: list[dict[str, Any]]) -> str:
    rows: list[dict[str, Any]] = []
    for item in results:
        rows.append(
            {
                "status": item.get("status"),
                "device_ip": item.get("device_ip"),
                "label": item.get("label"),
                "vendor": item.get("vendor"),
                "model": item.get("model"),
                "operation": item.get("operation") or item.get("capability") or "",
                "hash": item.get("command_hash") or (item.get("backup") or {}).get("config_hash") or "",
                "allowed": item.get("allowed", ""),
                "error": item.get("error", ""),
            }
        )
    return _table(
        ["status", "device_ip", "label", "vendor", "model", "operation", "hash", "allowed", "error"],
        rows,
        title=f"{command} results",
    )


def _format_workflow_results(results: list[dict[str, Any]]) -> str:
    return _table(
        [
            "device_ip",
            "label",
            "vendor",
            "model",
            "backup_status",
            "dry_run_status",
            "evaluate_status",
            "allowed",
            "command_hash",
            "error",
        ],
        results,
        title="Workflow results",
    )


def _format_next_execute_commands(results: list[dict[str, Any]]) -> str:
    commands = [str(item.get("next_execute_command")) for item in results if item.get("next_execute_command")]
    if not commands:
        return "Next execute commands: none"
    lines = ["Next execute commands", "---------------------"]
    lines.extend(f"  {index}. {command}" for index, command in enumerate(commands, start=1))
    return "\n".join(lines)


def _format_list(title: str, values: Any) -> str:
    if not values:
        return f"{title}: none"
    if not isinstance(values, list):
        values = [values]
    lines = [f"{title}:"]
    lines.extend(f"  - {value}" for value in values)
    return "\n".join(lines)


def _table(columns: list[str], rows: list[dict[str, Any]], *, title: str) -> str:
    if not rows:
        return f"{title}\n{'-' * len(title)}\n(no rows)"
    string_rows = [{column: _table_value(row.get(column)) for column in columns} for row in rows]
    widths = {
        column: min(48, max(len(column), *(len(row[column]) for row in string_rows)))
        for column in columns
    }
    header = "  ".join(column[: widths[column]].ljust(widths[column]) for column in columns)
    separator = "  ".join("-" * widths[column] for column in columns)
    body = [
        "  ".join(row[column][: widths[column]].ljust(widths[column]) for column in columns)
        for row in string_rows
    ]
    return "\n".join([title, "-" * len(title), header, separator, *body])


def _table_value(value: Any) -> str:
    if isinstance(value, bool):
        return _yes_no(value)
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return str(value).replace("\n", " ")


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _available(value: Any) -> str:
    return "available" if value else "missing"


def _enabled_disabled(value: Any) -> str:
    return "enabled" if value else "disabled"


if __name__ == "__main__":
    main(sys.argv[1:])
