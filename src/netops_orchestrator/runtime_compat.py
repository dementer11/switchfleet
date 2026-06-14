from __future__ import annotations

import os
from typing import Any, Literal

from app.core.transport_strategy import DeviceFamily, TransportDecision, TransportKind
from app.services.driver_capability_matrix import DriverCapabilityMatrix

from .models import CommandPhase, CommandPlan, Device


LegacyTransportPreference = Literal["netmiko", "paramiko", "custom_cli", "icmp_only", "unsupported"]

REAL_APPLY_DISABLED_MESSAGE = (
    "Legacy CLI real apply is disabled. This path requires the future Apply Safety Kernel "
    "and lab-only real apply stage before SSH config execution can be enabled."
)


class LegacyRuntimeSafetyError(RuntimeError):
    """Raised when legacy CLI execution would bypass the unified runtime safety model."""


LEGACY_DRIVER_TO_FAMILY: dict[str, DeviceFamily] = {
    "cisco_ios": DeviceFamily.cisco_ios,
    "huawei_vrp": DeviceFamily.huawei_vrp,
    "comware_smb": DeviceFamily.hpe_comware,
    "comware_legacy": DeviceFamily.hpe_comware,
    "comware7": DeviceFamily.hpe_comware,
    "hpe_procurve": DeviceFamily.hpe_procurve,
    "dell_powerconnect": DeviceFamily.dell_os,
    "eltex_mes": DeviceFamily.eltex,
    "bulat_bs": DeviceFamily.bulat,
    "unsupported_cli": DeviceFamily.unknown,
}

LEGACY_READ_ONLY_DRIVER_TO_FAMILY: dict[str, DeviceFamily] = {
    "qtech_qsw": DeviceFamily.qtech,
}


def runtime_decision_for_device(device: Device) -> TransportDecision:
    metadata = device.metadata or {}
    if _device_is_explicitly_non_configurable(device):
        return DriverCapabilityMatrix().decide(
            vendor=device.vendor,
            model=device.model,
            platform=_metadata_value(metadata, "platform"),
            device_id=device.ip_address,
            hostname=device.label,
        )
    driver_name = _metadata_value(metadata, "driver_name") or _metadata_value(metadata, "driver")
    family = _metadata_value(metadata, "family")
    return DriverCapabilityMatrix().decide(
        vendor=device.vendor,
        model=device.model,
        platform=_metadata_value(metadata, "platform"),
        driver_name=driver_name,
        family=family,
        device_id=device.ip_address,
        hostname=device.label,
    )


def runtime_decision_for_plan(plan: CommandPlan) -> TransportDecision:
    family = LEGACY_DRIVER_TO_FAMILY.get(plan.driver)
    if family is None and plan.read_only:
        family = LEGACY_READ_ONLY_DRIVER_TO_FAMILY.get(plan.driver)
    if family is None:
        device_decision = runtime_decision_for_device(plan.device)
        family = device_decision.family if device_decision.family != DeviceFamily.unknown else None
    return DriverCapabilityMatrix().decide(
        vendor=plan.device.vendor,
        model=plan.device.model,
        platform=_metadata_value(plan.device.metadata or {}, "platform"),
        family=family,
        device_id=plan.device.ip_address,
        hostname=plan.device.label,
    )


def assert_plan_runtime_safe(
    plan: CommandPlan,
    operation: str | None = None,
    allow_real_apply: bool = False,
) -> None:
    requested_operation = operation or plan.operation
    decision = runtime_decision_for_plan(plan)

    if decision.selected_transport in {TransportKind.unsupported, TransportKind.icmp_only}:
        raise LegacyRuntimeSafetyError(
            f"CLI transport is unavailable for {decision.family.value}: "
            f"{decision.unsupported_reason or 'runtime profile is not configurable'}"
        )

    if _plan_requires_config_apply(plan, requested_operation):
        env_requested = _legacy_apply_env_requested()
        suffix = " Environment flag requested real apply, but this stage still blocks it." if env_requested else ""
        raise LegacyRuntimeSafetyError(REAL_APPLY_DISABLED_MESSAGE + suffix)

    if not decision.read_only_allowed:
        raise LegacyRuntimeSafetyError(
            f"Read-only CLI operation is not supported for {decision.family.value}: "
            f"{decision.unsupported_reason or 'read-only runtime is unavailable'}"
        )

    if allow_real_apply:
        raise LegacyRuntimeSafetyError(REAL_APPLY_DISABLED_MESSAGE)


def assert_legacy_cli_apply_blocked() -> None:
    suffix = " Environment flag requested real apply, but this stage still blocks it." if _legacy_apply_env_requested() else ""
    raise LegacyRuntimeSafetyError(REAL_APPLY_DISABLED_MESSAGE + suffix)


def legacy_driver_name_for_device(device: Device) -> str:
    decision = runtime_decision_for_device(device)
    return decision.driver_name


def legacy_transport_preference_for_decision(decision: TransportDecision) -> LegacyTransportPreference:
    return decision.selected_transport.value  # type: ignore[return-value]


def explain_runtime_decision(device_or_plan: Device | CommandPlan) -> dict[str, Any]:
    decision = (
        runtime_decision_for_plan(device_or_plan)
        if isinstance(device_or_plan, CommandPlan)
        else runtime_decision_for_device(device_or_plan)
    )
    explanation = decision.to_safe_dict()
    explanation["legacy_transport_preference"] = legacy_transport_preference_for_decision(decision)
    explanation["legacy_real_apply_enabled_env"] = _legacy_apply_env_requested()
    explanation["legacy_real_apply_allowed"] = False
    return explanation


def _metadata_value(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return str(value).strip() if value is not None and str(value).strip() else None


def _device_is_explicitly_non_configurable(device: Device) -> bool:
    text = f"{device.vendor} {device.model}".casefold()
    return "unknown product" in text or "unknown snmp product" in text or "icmp" in text


def _plan_requires_config_apply(plan: CommandPlan, operation: str) -> bool:
    if operation != "backup" and not plan.read_only:
        return True
    for step in plan.execution_steps:
        if step.phase in {CommandPhase.config, CommandPhase.save}:
            return True
        if not step.read_only and operation != "backup":
            return True
    return False


def _legacy_apply_env_requested() -> bool:
    value = os.getenv("NCP_LEGACY_CLI_REAL_APPLY") or os.getenv("NCP_ALLOW_REAL_DEVICE_APPLY")
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}
