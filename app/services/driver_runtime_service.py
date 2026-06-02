from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import ConfigApplyNotAllowedError, NotFoundError
from app.core.transport_strategy import DeviceFamily, DriverRuntimeProfile, TransportDecision, TransportKind
from app.db.models.device import Device
from app.schemas.driver_runtime import DriverRuntimeSafetyReport, DriverRuntimeSummary
from app.services.driver_capability_matrix import DriverCapabilityMatrix
from app.services.transport_runtime import TransportRuntime


class DriverRuntimeService:
    def __init__(
        self,
        session: Session | None = None,
        matrix: DriverCapabilityMatrix | None = None,
        settings: Settings | None = None,
    ):
        self.session = session
        self.matrix = matrix or DriverCapabilityMatrix()
        self.settings = settings or get_settings()
        self.runtime = TransportRuntime(self.matrix)

    def get_transport_decision_for_device(self, device_id: str) -> TransportDecision:
        if self.session is None:
            raise NotFoundError("Database session is required for device runtime decisions")
        device = self.session.scalar(select(Device).where(Device.id == device_id))
        if device is None:
            raise NotFoundError(f"Device {device_id!r} not found")
        return self.runtime.decide_transport(device)

    def get_transport_decision_for_inventory_record(self, record: dict[str, Any]) -> TransportDecision:
        return self.matrix.decide(
            vendor=str(record.get("vendor") or ""),
            model=str(record.get("model") or ""),
            platform=str(record.get("platform") or ""),
            driver_name=str(record.get("driver_name") or "") or None,
            family=str(record.get("family") or "") or None,
            device_id=str(record.get("device_id") or "") or None,
            hostname=str(record.get("hostname") or "") or None,
        )

    def decide(
        self,
        *,
        vendor: str,
        model: str | None = None,
        platform: str | None = None,
        driver_name: str | None = None,
        family: str | None = None,
    ) -> TransportDecision:
        return self.matrix.decide(vendor=vendor, model=model, platform=platform, driver_name=driver_name, family=family)

    def list_supported_driver_profiles(self) -> tuple[DriverRuntimeProfile, ...]:
        return self.matrix.list_profiles()

    def get_driver_profile(self, family: str | DeviceFamily) -> DriverRuntimeProfile:
        profile = self.matrix.get_profile(family)
        if profile is None:
            raise NotFoundError(f"Driver runtime profile {family!r} not found")
        return profile

    def assert_read_only_supported(self, decision: TransportDecision) -> None:
        if not self.runtime.supports_read_only(decision):
            raise ConfigApplyNotAllowedError(f"Read-only runtime is not supported for {decision.driver_name}")

    def assert_config_apply_blocked(self, decision: TransportDecision) -> None:
        self.runtime.assert_config_apply_blocked(decision)

    def build_runtime_summary(self) -> DriverRuntimeSummary:
        profiles = self.list_supported_driver_profiles()
        by_transport = Counter(profile.preferred_transport for profile in profiles)
        real_apply_certified_count = sum(1 for profile in profiles if profile.real_apply_certified)
        warnings = [
            "Driver runtime is read-only/decision-only in this stage.",
            "config_apply_allowed is false for every runtime decision.",
            "Real apply certification count must remain zero until a separate lab-only stage.",
        ]
        if self.settings.allow_real_device_apply:
            warnings.append("NCP_ALLOW_REAL_DEVICE_APPLY is true in settings; runtime decisions still do not allow apply.")
        return DriverRuntimeSummary(
            total_profiles=len(profiles),
            netmiko_profiles=by_transport[TransportKind.netmiko],
            paramiko_profiles=by_transport[TransportKind.paramiko],
            custom_cli_profiles=by_transport[TransportKind.custom_cli],
            icmp_only_profiles=by_transport[TransportKind.icmp_only],
            unsupported_profiles=by_transport[TransportKind.unsupported],
            config_apply_supported_count=sum(1 for profile in profiles if profile.config_apply_supported),
            real_apply_certified_count=real_apply_certified_count,
            config_apply_allowed_globally=False,
            safety_warnings=warnings,
        )

    def build_safety_report(self) -> DriverRuntimeSafetyReport:
        summary = self.build_runtime_summary()
        return DriverRuntimeSafetyReport(
            real_apply_enabled=bool(self.settings.allow_real_device_apply),
            real_apply_certified_count=summary.real_apply_certified_count,
            config_apply_allowed_globally=False,
            apply_endpoint_added=False,
            destructive_run_endpoint_added=False,
            session_opening_from_api=False,
            warnings=[
                "No driver-runtime endpoint opens SSH sessions.",
                "No driver-runtime endpoint applies configuration.",
                "Unsupported, GenericSSH, ICMP, Bulat, and Eltex destructive apply paths fail closed.",
            ],
        )
