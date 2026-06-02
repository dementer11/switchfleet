from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rbac import Actor, Permission, Role
from app.core.vendor_driver_contracts import VendorOperation
from app.db.models.change_execution import ChangeExecution, ChangeExecutionLock
from app.db.models.config_backup import ConfigSnapshot
from app.db.models.device import Device
from app.db.models.lab_validation import LabDriverValidation
from app.db.session import SessionLocal
from app.repositories.change_executions import ChangeExecutionRepository
from app.schemas.credential_vault import CredentialSecretCreate
from app.schemas.lab_apply import LabApplyCommand, LabApplyEvaluateRequest
from app.services.apply_safety_kernel import ApplySafetyKernel, REQUIRED_GATES
from app.services.audit_service import AuditService
from app.services.credential_vault_service import CredentialVaultService
from app.services.driver_capability_matrix import DriverCapabilityMatrix
from app.services.lab_apply_service import LabApplyService
from app.services.lab_backup_runner import LabBackupRunner
from app.services.vendor_command_templates import VendorCommandTemplateService, command_hash


DEFAULT_ACTOR = "lab-operator"
DEFAULT_ROLES = frozenset({Role.network_admin})


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="lab", description="Runnable lab prototype helper.")
    parser.add_argument("--actor", default=DEFAULT_ACTOR)
    parser.add_argument("--roles", default="network_admin")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("bootstrap-admin", help="Print prototype admin/operator bootstrap details")

    add_device = sub.add_parser("add-device", help="Add or update one lab device")
    _device_args(add_device)

    import_devices = sub.add_parser("import-devices", help="Import lab devices from JSON/YAML")
    import_devices.add_argument("path", type=Path)

    sub.add_parser("list-devices", help="List lab prototype devices")

    add_credential = sub.add_parser("add-credential", help="Create encrypted credential ref")
    add_credential.add_argument("--name", required=True)
    add_credential.add_argument("--username", required=True)
    add_credential.add_argument("--password-prompt", action="store_true")
    add_credential.add_argument("--password-env")
    add_credential.add_argument("--purpose", default="lab_apply")

    check_runtime = sub.add_parser("check-runtime", help="Show driver runtime decision")
    check_runtime.add_argument("--device", required=True)

    backup = sub.add_parser("backup", help="Capture sanitized read-only lab backup")
    backup.add_argument("--device", required=True)
    backup.add_argument("--credential", required=True)

    dry_run = sub.add_parser("dry-run", help="Render redacted command plan and hash")
    _operation_args(dry_run)

    evaluate = sub.add_parser("evaluate-apply", help="Evaluate lab apply gates")
    _apply_args(evaluate)

    execute = sub.add_parser("execute-apply", help="Execute fake or real lab apply after gates pass")
    _apply_args(execute)
    execute.add_argument("--real-lab", action="store_true")

    audit = sub.add_parser("audit-tail", help="Show recent audit events")
    audit.add_argument("--limit", type=int, default=20)

    args = parser.parse_args(argv)
    session = SessionLocal()
    actor = _actor(args)
    try:
        result = _dispatch(session, args, actor)
        session.commit()
    except Exception:
        session.rollback()
        raise
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _dispatch(session: Session, args: argparse.Namespace, actor: Actor) -> dict[str, Any]:
    if args.command == "bootstrap-admin":
        AuditService(session).write(
            actor=actor.username,
            action="lab_prototype.bootstrap_checked",
            object_type="prototype",
            object_id="lab",
            metadata={"roles": sorted(role.value for role in actor.roles)},
        )
        return {
            "actor": actor.username,
            "roles": sorted(role.value for role in actor.roles),
            "headers": {"X-Actor": actor.username, "X-Roles": ",".join(sorted(role.value for role in actor.roles))},
            "required_env": [
                "NCP_SECRET_KEY",
                "NCP_ALLOW_REAL_DEVICE_APPLY=true",
                "NCP_LAB_REAL_APPLY_ENABLED=true",
                "NCP_PRODUCTION_REAL_APPLY_ENABLED=false",
                "NCP_LAB_DEVICE_ALLOWLIST=<device id, hostname, or management ip>",
            ],
        }
    if args.command == "add-device":
        return {"device": _read_device(_upsert_device(session, vars(args)))}
    if args.command == "import-devices":
        devices = [_upsert_device(session, item) for item in _load_devices(args.path)]
        return {
            "devices": [_read_device(device) for device in devices],
            "allowlist_hint": "Set NCP_LAB_DEVICE_ALLOWLIST to comma-separated device ids, hostnames, or management IPs.",
        }
    if args.command == "list-devices":
        devices = list(session.scalars(select(Device).order_by(Device.hostname, Device.ip_address)).all())
        return {"devices": [_read_device(device) for device in devices]}
    if args.command == "add-credential":
        _require_manage_secrets(actor)
        secret = _read_secret(args)
        created = CredentialVaultService(session).create_secret(
            CredentialSecretCreate(name=args.name, username=args.username, secret=secret, purpose=args.purpose),
            actor=actor.username,
        )
        return {"credential_ref": created.id, "name": created.name, "username": created.username, "has_secret": created.has_secret}
    if args.command == "check-runtime":
        device = _resolve_device(session, args.device)
        decision = DriverCapabilityMatrix().decide(
            vendor=device.vendor,
            model=device.model,
            platform=device.platform,
            driver_name=device.driver_name or None,
            device_id=str(device.id),
            hostname=device.hostname,
        )
        contract = __import__("app.core.vendor_driver_contracts", fromlist=["get_vendor_driver_contract"]).get_vendor_driver_contract(
            decision.family
        )
        data = decision.to_safe_dict()
        data["apply_support_level"] = contract.apply_support_level.value
        data["lab_certified"] = contract.lab_certified
        data["production_certified"] = contract.production_certified
        return {"runtime_decision": data}
    if args.command == "backup":
        _require_permission(actor, Permission.use_credential_secrets)
        device = _resolve_device(session, args.device)
        credential_ref = _resolve_credential_ref(session, args.credential)
        result = LabBackupRunner(session, settings=get_settings()).backup_device(device, credential_ref=credential_ref, actor=actor.username)
        return result.__dict__
    if args.command == "dry-run":
        device = _resolve_device(session, args.device)
        rendered = _render_commands(device, _operation(args), _command_parameters(args))
        return {
            "device": _read_device(device),
            "operation": _operation(args).value,
            "commands": [command.to_safe_dict() for command in rendered],
            "command_hash": command_hash(rendered),
            "required_gates": REQUIRED_GATES,
        }
    if args.command == "evaluate-apply":
        payload = _build_apply_payload(session, args)
        decision = ApplySafetyKernel(session, settings=get_settings()).evaluate(
            payload,
            actor_permissions=_permission_values(actor),
        ).decision
        return decision.model_dump(mode="json")
    if args.command == "execute-apply":
        if args.real_lab and not args.simulation_hash:
            raise SystemExit("Real lab execution requires --simulation-hash from a prior dry-run")
        payload = _build_apply_payload(session, args)
        payload.use_fake_transport = not args.real_lab
        response = LabApplyService(session, settings=get_settings()).execute(
            payload,
            actor=actor.username,
            actor_permissions=_permission_values(actor),
        )
        return response.model_dump(mode="json")
    if args.command == "audit-tail":
        events = AuditService(session).list()
        return {"events": [event.model_dump(mode="json") for event in events[: args.limit]]}
    raise SystemExit(f"Unsupported lab command: {args.command}")


def _device_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--management-ip", required=True)
    parser.add_argument("--vendor", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--platform", default="")
    parser.add_argument("--driver-name", default="")
    parser.add_argument("--site", default="lab")


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
    parser.add_argument("--backup-snapshot")
    parser.add_argument("--lab-validation")
    parser.add_argument("--approval", choices=["approved", "rejected", "pending"], default=None)
    parser.add_argument("--simulation-hash")
    parser.add_argument("--lock", action="store_true")
    parser.add_argument("--prototype-auto-gates", action="store_true")


def _actor(args: argparse.Namespace) -> Actor:
    try:
        roles = frozenset(Role(role.strip()) for role in str(args.roles).split(",") if role.strip()) or DEFAULT_ROLES
    except ValueError as exc:
        raise SystemExit(f"Invalid role in --roles: {args.roles}") from exc
    return Actor(username=str(args.actor), roles=roles)


def _permission_values(actor: Actor) -> set[str]:
    return {permission.value for permission in actor.permissions}


def _require_manage_secrets(actor: Actor) -> None:
    _require_permission(actor, Permission.manage_credential_secrets)


def _require_permission(actor: Actor, permission: Permission) -> None:
    if permission not in actor.permissions:
        raise SystemExit(f"Actor must have {permission.value} permission")


def _upsert_device(session: Session, item: dict[str, Any]) -> Device:
    hostname = str(item["hostname"])
    management_ip = str(item.get("management_ip") or item.get("management-ip") or item.get("ip_address") or item.get("ip-address"))
    tags = _lab_tags(item.get("tags"))
    stored = session.scalar(select(Device).where(or_(Device.hostname == hostname, Device.ip_address == management_ip)))
    if stored is None:
        stored = Device(
            hostname=hostname,
            ip_address=management_ip,
            management_ip=management_ip,
            vendor=str(item["vendor"]),
            model=str(item["model"]),
            platform=str(item.get("platform") or ""),
            driver_name=str(item.get("driver_name") or item.get("driver-name") or ""),
            site=str(item.get("site") or "lab"),
            tags=tags,
            status="known",
        )
        session.add(stored)
    else:
        stored.management_ip = management_ip
        stored.vendor = str(item["vendor"])
        stored.model = str(item["model"])
        stored.platform = str(item.get("platform") or "")
        stored.driver_name = str(item.get("driver_name") or item.get("driver-name") or stored.driver_name)
        stored.site = str(item.get("site") or stored.site or "lab")
        stored.tags = tags
    session.flush()
    return stored


def _lab_tags(raw_tags: Any) -> dict[str, Any]:
    tags = dict(raw_tags or {})
    if tags.get("lab") is False:
        raise SystemExit("Runnable lab prototype refuses devices explicitly tagged lab=false")
    environment = str(tags.get("environment") or "").casefold()
    if environment and environment != "lab":
        raise SystemExit("Runnable lab prototype refuses non-lab device environment tags")
    tags["lab"] = True
    tags["environment"] = "lab"
    return tags


def _load_devices(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.casefold() == ".json":
        payload = json.loads(text)
    else:
        payload = _load_minimal_yaml(text)
    if isinstance(payload, list):
        devices = payload
    elif isinstance(payload, dict):
        devices = payload.get("devices", [])
    else:
        devices = []
    if not isinstance(devices, list):
        raise SystemExit("Device file must contain a devices list")
    return [dict(device) for device in devices]


def _load_minimal_yaml(text: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return _parse_device_yaml_subset(text)
    loaded = yaml.safe_load(text) or {}
    if not isinstance(loaded, dict):
        raise SystemExit("YAML device file must contain a mapping")
    return loaded


def _parse_device_yaml_subset(text: str) -> dict[str, Any]:
    devices: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_tags = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "devices:":
            continue
        if stripped.startswith("- "):
            if current is not None:
                devices.append(current)
            current = {}
            in_tags = False
            key, value = _split_yaml_pair(stripped[2:])
            current[key] = value
            continue
        if current is None:
            continue
        if stripped == "tags:":
            current["tags"] = {}
            in_tags = True
            continue
        key, value = _split_yaml_pair(stripped)
        if in_tags:
            current.setdefault("tags", {})[key] = value
        else:
            current[key] = value
    if current is not None:
        devices.append(current)
    return {"devices": devices}


def _split_yaml_pair(value: str) -> tuple[str, Any]:
    if ":" not in value:
        raise SystemExit(f"Unsupported YAML line: {value}")
    key, raw_value = value.split(":", 1)
    raw_value = raw_value.strip().strip('"').strip("'")
    if raw_value.casefold() == "true":
        parsed: Any = True
    elif raw_value.casefold() == "false":
        parsed = False
    else:
        parsed = raw_value
    return key.strip(), parsed


def _resolve_device(session: Session, value: str) -> Device:
    statement = select(Device).where(
        or_(
            Device.hostname == value,
            Device.ip_address == value,
            Device.management_ip == value,
        )
    )
    if _looks_uuid(value):
        statement = select(Device).where(Device.id == value)
    device = session.scalar(statement)
    if device is None:
        raise SystemExit(f"Device {value!r} not found")
    return device


def _resolve_credential_ref(session: Session, value: str) -> str:
    service = CredentialVaultService(session)
    for secret in service.list_metadata(active=True):
        if secret.id == value or secret.name == value:
            return secret.id
    raise SystemExit(f"Credential {value!r} not found")


def _read_secret(args: argparse.Namespace) -> str:
    if args.password_env:
        secret = os.getenv(args.password_env)
        if secret is None:
            raise SystemExit(f"Environment variable {args.password_env!r} is not set")
        return secret
    if args.password_prompt:
        return getpass.getpass("Credential password: ")
    raise SystemExit("Use --password-prompt or --password-env; plaintext password arguments are intentionally unsupported")


def _read_device(device: Device) -> dict[str, Any]:
    return {
        "id": str(device.id),
        "hostname": device.hostname,
        "management_ip": str(device.management_ip or ""),
        "vendor": device.vendor,
        "model": device.model,
        "platform": device.platform,
        "driver_name": device.driver_name,
        "site": device.site,
        "tags": device.tags,
    }


def _operation(args: argparse.Namespace) -> VendorOperation:
    return VendorOperation(str(args.operation))


def _command_parameters(args: argparse.Namespace) -> dict[str, Any]:
    operation = _operation(args)
    if operation == VendorOperation.vlan_create:
        return {"vlan_id": args.vlan_id, "name": args.name}
    if operation == VendorOperation.password_change:
        password = _read_new_password(args)
        return {"username": args.username, "password": password, "level": args.level}
    if operation == VendorOperation.vlan_assign_port:
        return {"interface": args.interface, "vlan_id": args.vlan_id}
    return {}


def _read_new_password(args: argparse.Namespace) -> str:
    if args.new_password_env:
        value = os.getenv(args.new_password_env)
        if value is None:
            raise SystemExit(f"Environment variable {args.new_password_env!r} is not set")
        return value
    if args.new_password_prompt:
        return getpass.getpass("New password: ")
    raise SystemExit("Password operations require --new-password-prompt or --new-password-env")


def _render_commands(device: Device, operation: VendorOperation, parameters: dict[str, Any]) -> list[Any]:
    decision = DriverCapabilityMatrix().decide(
        vendor=device.vendor,
        model=device.model,
        platform=device.platform,
        driver_name=device.driver_name or None,
        device_id=str(device.id),
        hostname=device.hostname,
    )
    return VendorCommandTemplateService().render(decision.family, operation, parameters)


def _build_apply_payload(session: Session, args: argparse.Namespace) -> LabApplyEvaluateRequest:
    device = _resolve_device(session, args.device)
    if args.prototype_auto_gates:
        _assert_prototype_auto_gates_allowed(session, device)
    operation = _operation(args)
    parameters = _command_parameters(args)
    rendered = _render_commands(device, operation, parameters)
    hash_value = command_hash(rendered)
    backup_snapshot = args.backup_snapshot or (_latest_snapshot_id(session, device) if args.prototype_auto_gates else None)
    validation_id = args.lab_validation or (_create_lab_validation(session, device, operation) if args.prototype_auto_gates else None)
    lock_id = _create_lock(session, device, operation) if (args.lock or args.prototype_auto_gates) else None
    approval_status = args.approval or ("approved" if args.prototype_auto_gates else None)
    rollback = [LabApplyCommand(command=f"rollback preview for {operation.value}", secret=False)]
    return LabApplyEvaluateRequest(
        device_id=str(device.id),
        operation=operation,
        credential_ref=_resolve_credential_ref(session, args.credential),
        command_parameters=parameters,
        command_plan=[LabApplyCommand(command=command.command, secret=command.secret) for command in rendered],
        rollback_plan=rollback,
        backup_snapshot_id=backup_snapshot,
        lab_validation_id=validation_id,
        approval_id="prototype-approved" if approval_status == "approved" else None,
        approval_status=approval_status,
        dry_run_hash=hash_value,
        simulation_hash=args.simulation_hash or hash_value,
        lock_id=lock_id,
        allow_lab_candidate=True,
        use_fake_transport=True,
    )


def _latest_snapshot_id(session: Session, device: Device) -> str | None:
    snapshot = session.scalar(
        select(ConfigSnapshot)
        .where(ConfigSnapshot.device_id == device.id, ConfigSnapshot.sanitized.is_(True))
        .order_by(ConfigSnapshot.collected_at.desc(), ConfigSnapshot.created_at.desc())
    )
    return str(snapshot.id) if snapshot else None


def _assert_prototype_auto_gates_allowed(session: Session, device: Device) -> None:
    tags = device.tags or {}
    is_lab = bool(tags.get("lab") is True or str(tags.get("environment") or "").casefold() == "lab")
    if not is_lab:
        raise SystemExit("Prototype auto-gates are allowed only for explicitly lab-tagged devices")
    allowlist = {item.strip() for item in get_settings().lab_device_allowlist.split(",") if item.strip()}
    identifiers = {str(device.id), device.hostname or "", device.management_ip or "", device.ip_address or ""}
    if not allowlist.intersection(identifiers):
        raise SystemExit("Prototype auto-gates require NCP_LAB_DEVICE_ALLOWLIST to include the device")
    if _latest_snapshot_id(session, device) is None:
        raise SystemExit("Prototype auto-gates require an existing sanitized backup snapshot")
    reserved_lock = session.scalar(
        select(ChangeExecutionLock).where(ChangeExecutionLock.device_id == device.id, ChangeExecutionLock.status == "reserved")
    )
    if reserved_lock is not None:
        raise SystemExit("Prototype auto-gates refuse to create a second reserved lock for this device")


def _create_lab_validation(session: Session, device: Device, operation: VendorOperation) -> str:
    validation = LabDriverValidation(
        vendor=device.vendor,
        model_pattern=device.model,
        driver_name=device.driver_name,
        capability=operation.value,
        status="approved",
        validated_by="prototype-auto-gates",
        lab_environment="lab",
        evidence_summary="Runnable lab prototype auto-gate stub; verify manually before production use.",
    )
    session.add(validation)
    session.flush()
    return str(validation.id)


def _create_lock(session: Session, device: Device, operation: VendorOperation) -> str:
    repo = ChangeExecutionRepository(session)
    execution: ChangeExecution = repo.create_execution(
        title=f"Prototype {operation.value} for {device.hostname or device.ip_address}",
        change_type=operation.value,
        source_type="prototype",
        requested_by=DEFAULT_ACTOR,
    )
    lock = repo.create_locks(
        execution.id,
        [
            {
                "lock_type": "device",
                "target_type": "device",
                "target_id": device.id,
                "device_id": device.id,
                "reason": "runnable lab prototype",
            }
        ],
    )[0]
    return str(lock.id)


def _looks_uuid(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F-]{36}", value))


if __name__ == "__main__":
    main(sys.argv[1:])
