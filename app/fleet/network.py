"""Execution for approved fleet plans; no database policy or approval logic lives here."""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

from app.core.transport_strategy import DeviceFamily, DriverCapability, TransportDecision, TransportKind
from app.core.vendor_driver_contracts import get_vendor_driver_contract
from app.services.real_lab_apply_runner import (
    NetmikoCommandTransport,
    ParamikoCommandTransport,
    clean_backup_output,
    output_has_paging_marker,
    run_read_only_backup_command,
)
from app.services.transport_runtime import RuntimeCredentials
from app.utils.config_sanitizer import sanitize_config
from app.utils.masking import mask_secrets

_DRIVERS = {
    "cisco_ios": "CiscoIOSDriver",
    "huawei_vrp": "HuaweiVRPDriver",
    "hpe_comware": "HPComwareDriver",
    "hpe_procurve": "HPEProCurveDriver",
    "dell_os": "DellPowerConnectDriver",
    "bulat": "BulatBSDriver",
    "qtech": "QtechQswDriver",
    "eltex": "EltexMESDriver",
    "generic_ssh": "GenericSSHDriver",
}
_SUPPORTED_FAMILIES = set(_DRIVERS)


def _create_transport(plan: dict[str, Any], credentials: dict[str, Any], timeout: int) -> Any:
    family = DeviceFamily(str(plan.get("family", "unknown")))
    driver = _DRIVERS.get(family.value, "UnsupportedDriver")
    custom = family in {DeviceFamily.bulat, DeviceFamily.qtech, DeviceFamily.eltex, DeviceFamily.generic_ssh}
    decision = TransportDecision(
        vendor=str(plan.get("family", "")),
        family=family,
        selected_transport=TransportKind.paramiko if custom else TransportKind.netmiko,
        driver_name=driver,
        capabilities=frozenset({DriverCapability.read_only, DriverCapability.config_staging}),
        read_only_allowed=True,
        config_apply_allowed=True,
        fallback_transport=None,
        platform=family.value,
        model=None,
        device_id=str(plan.get("device_id", "")),
    )
    runtime_credentials = RuntimeCredentials(
        username=str(credentials.get("username") or ""),
        password=str(credentials.get("password") or ""),
        enable_password=str(credentials.get("enable_password") or "") or None,
    )
    transport_type = ParamikoCommandTransport if custom else NetmikoCommandTransport
    return transport_type(decision, runtime_credentials, str(plan["ip_address"]), int(plan.get("port", 22)), timeout)


def execute_device(
    plan: dict[str, Any],
    credentials: dict[str, Any],
    timeout: int = 30,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Execute a plan from the caller's approved-plan flow.

    Mutating/exec plans always capture a fresh backup before sending any
    commands. This layer does not make or infer approval decisions.
    """
    started = time.monotonic()
    device_id = str(plan.get("device_id", ""))
    operation = str(plan.get("operation", ""))
    family = str(plan.get("family", "unknown"))
    secret_keys = {"password", "enable_password", "new_password", "private_key", "private_key_passphrase", "passphrase"}
    secret_values = (
        [str(value) for key, value in credentials.items() if str(key).casefold() in secret_keys and value is not None and str(value)]
        if isinstance(credentials, dict)
        else []
    )
    secret_values = list(dict.fromkeys(value for value in secret_values if value))
    output_parts: list[str] = []
    backup_text: str | None = None
    changed = False
    verification = "not_run"
    transport: Any | None = None

    def is_cancelled() -> bool:
        try:
            return bool(cancelled and cancelled())
        except Exception:  # noqa: BLE001 - callback failure fails closed as cancellation
            return True

    def safe(text: Any) -> str:
        return mask_secrets(str(text or ""), explicit_secrets=secret_values)

    def result(status: str, error: str | None = None) -> dict[str, Any]:
        sanitized_backup = None
        if backup_text is not None:
            sanitized_backup = safe(sanitize_config(backup_text).text)
        sanitized_output = sanitize_config("\n".join(output_parts)).text
        return {
            "device_id": device_id,
            "operation": operation,
            "status": status,
            "changed": changed,
            "output": safe(sanitized_output),
            "backup_text": sanitized_backup,
            "error": safe(error) if error else None,
            "duration_seconds": max(0.0, time.monotonic() - started),
            "verification": verification,
        }

    if plan.get("status") == "unsupported" or not plan.get("ip_address"):
        return result("unsupported", str(plan.get("error") or "Unsupported or invalid device plan"))
    if family not in _SUPPORTED_FAMILIES or (family == "generic_ssh" and operation != "commands"):
        return result("unsupported", f"CLI operation is unsupported for family {family!r}")
    if not isinstance(credentials, dict) or not credentials.get("username") or not credentials.get("password"):
        return result("failed", "SSH username and password are required")
    if is_cancelled():
        return result("cancelled")

    try:
        rendered = _commands_for_execution(plan, credentials)
        if operation in {"facts", "backup"}:
            if not plan.get("commands"):
                return result("unsupported", "Read-only plan has no commands")
        else:
            if not rendered and not plan.get("save_commands"):
                return result("unsupported", "Mutating plan has no commands")
            if not plan.get("backup_commands"):
                return result("failed", "A pre-change backup is required but no backup command is defined")
        transport = _create_transport(plan, credentials, max(1, int(timeout or plan.get("timeout", 30))))
        transport.open()
        contract = get_vendor_driver_contract(DeviceFamily(family))

        # Facts and backups have no mutation and do not trigger a second backup.
        if operation in {"facts", "backup"}:
            readonly_backup_fragments: list[str] = []
            for command in plan.get("setup_commands", []):
                if is_cancelled():
                    return result("cancelled")
                setup_result = transport.run_command(command, timeout_seconds=timeout)
                output_parts.append(setup_result.output)
                if not setup_result.success:
                    return result("failed", setup_result.error or f"Setup command failed: {command}")
            for command in plan.get("commands", []):
                if is_cancelled():
                    return result("cancelled")
                command_result = run_read_only_backup_command(transport, command, timeout_seconds=timeout)
                if not command_result.success:
                    if operation == "backup" and not _has_vendor_error(command_result.output, contract.error_patterns) and not output_has_paging_marker(command_result.output):
                        partial = clean_backup_output(command_result.output, command, _transport_decision(family, plan))
                        if partial.strip():
                            readonly_backup_fragments.append(partial)
                            backup_text = "\n".join(readonly_backup_fragments)
                    output_parts.append(command_result.output)
                    return result("failed", command_result.error or f"Read-only command failed: {command}")
                if _has_vendor_error(command_result.output, contract.error_patterns):
                    output_parts.append(command_result.output)
                    return result("failed", "Vendor error pattern detected in read-only command output")
                if output_has_paging_marker(command_result.output):
                    output_parts.append(command_result.output)
                    return result("failed", "Incomplete paged command output")
                cleaned = clean_backup_output(command_result.output, command, _transport_decision(family, plan))
                if not cleaned.strip():
                    output_parts.append(command_result.output)
                    return result("failed", "Read-only command returned no usable output")
                output_parts.append(cleaned)
                readonly_backup_fragments.append(cleaned)
            if operation == "backup":
                backup_text = "\n".join(readonly_backup_fragments)
            verification = "commands_completed"
            return result("succeeded")

        # A fresh backup is mandatory for every command or config operation.
        if operation not in {"facts", "backup"}:
            for command in plan.get("backup_setup_commands", []):
                if is_cancelled():
                    return result("cancelled")
                setup_result = transport.run_command(command, timeout_seconds=timeout)
                output_parts.append(setup_result.output)
                if not setup_result.success:
                    return result("failed", setup_result.error or f"Backup setup failed: {command}")
            backup_fragments: list[str] = []
            for command in plan.get("backup_commands", []):
                if is_cancelled():
                    backup_text = "\n".join(backup_fragments)
                    return result("cancelled")
                backup_result = run_read_only_backup_command(transport, command, timeout_seconds=timeout)
                if not backup_result.success:
                    if not _has_vendor_error(backup_result.output, contract.error_patterns) and not output_has_paging_marker(backup_result.output):
                        partial = clean_backup_output(backup_result.output, command, _transport_decision(family, plan))
                        if partial.strip():
                            backup_fragments.append(partial)
                            backup_text = "\n".join(backup_fragments)
                    output_parts.append(backup_result.output)
                    return result("failed", backup_result.error or "Pre-change backup failed")
                if _has_vendor_error(backup_result.output, contract.error_patterns):
                    output_parts.append(backup_result.output)
                    return result("failed", "Vendor error pattern detected in pre-change backup")
                if output_has_paging_marker(backup_result.output):
                    output_parts.append(backup_result.output)
                    return result("failed", "Pre-change backup output is incomplete")
                cleaned_backup = clean_backup_output(backup_result.output, command, _transport_decision(family, plan))
                if not cleaned_backup.strip():
                    output_parts.append(backup_result.output)
                    return result("failed", "Pre-change backup returned no usable configuration")
                backup_fragments.append(cleaned_backup)
                backup_text = "\n".join(backup_fragments)
            if not plan.get("backup_commands") or backup_text is None:
                return result("failed", "A pre-change backup is required but no backup command is defined")

        write_commands = [*rendered, *plan.get("save_commands", [])]
        for command in [*plan.get("setup_commands", []), *write_commands]:
            if is_cancelled():
                return result("cancelled")
            command_result = transport.run_command(str(command), timeout_seconds=timeout)
            output_parts.append(command_result.output)
            changed = changed or command in write_commands
            failed = not command_result.success or any(re.search(pattern, command_result.output, re.IGNORECASE) for pattern in contract.error_patterns)
            if failed:
                return result("failed", command_result.error or "Vendor command reported an error")
        for command in plan.get("verify_commands", []):
            if is_cancelled():
                return result("cancelled")
            verify_result = transport.run_command(str(command), timeout_seconds=timeout)
            output_parts.append(verify_result.output)
            if not verify_result.success or any(re.search(pattern, verify_result.output, re.IGNORECASE) for pattern in contract.error_patterns):
                return result("failed", verify_result.error or "Verification command failed")
        verification = "commands_completed"
        return result("succeeded")
    except Exception as exc:  # noqa: BLE001 - third-party SSH libraries expose varying exceptions; result() redacts them
        return result("failed", safe(exc))
    finally:
        if transport is not None:
            try:
                transport.close()
            except Exception:  # noqa: BLE001, S110 - close cleanup must not replace the execution result
                pass


def _commands_for_execution(plan: dict[str, Any], credentials: dict[str, Any]) -> list[str]:
    commands = [str(item) for item in plan.get("commands", [])]
    if str(plan.get("operation", "")) == "password_change":
        new_password = str(credentials.get("new_password") or "")
        if not new_password:
            raise ValueError("new_password credential is required")
        if "\n" in new_password or "\r" in new_password:
            raise ValueError("new_password must not contain newline")
        commands = [command.replace("__SWITCHFLEET_NEW_PASSWORD__", new_password) for command in commands]
    return commands


def _transport_decision(family: str, plan: dict[str, Any]) -> TransportDecision:
    family_enum = DeviceFamily(family)
    custom = family_enum in {DeviceFamily.bulat, DeviceFamily.qtech, DeviceFamily.eltex, DeviceFamily.generic_ssh}
    return TransportDecision(
        vendor=family,
        family=family_enum,
        selected_transport=TransportKind.paramiko if custom else TransportKind.netmiko,
        driver_name=_DRIVERS.get(family, "UnsupportedDriver"),
        capabilities=frozenset({DriverCapability.read_only}),
        read_only_allowed=True,
        device_id=str(plan.get("device_id", "")),
        platform=family,
    )


def _has_vendor_error(output: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, output, re.IGNORECASE) for pattern in patterns)
